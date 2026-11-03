"""The end-to-end command: reset, upload every contract-test sample, wait, check, render."""

import contextlib

import pytest
import sqlalchemy as sa

from pipeline.contracts import load_contracts
from pipeline.e2e import (
    Finished,
    check,
    db_now,
    render_pages,
    reset,
    run,
    samples,
    upload,
    wait_for_runs,
)
from pipeline.ingest import ingest_file
from pipeline.load import TABLES, RunRecord, finish_run, start_run

pytestmark = pytest.mark.db

KEY = "raw/cse-cic-ids2018/wednesday-14-02-2018.csv"


def ingest_on_upload(engine, bucket, workdir):
    """A sleep for wait_for_runs that does EventBridge's job: it ingests each raw/ key that
    has no run yet, as the job task would."""

    def sleep(_seconds):
        listed = bucket.client.list_objects_v2(Bucket=bucket.name, Prefix="raw/")
        keys = sorted(o["Key"] for o in listed.get("Contents", []))
        with engine.connect() as conn:
            seen = set(conn.execute(sa.text("SELECT file_key FROM ingestion_runs")).scalars())
        for key in keys:
            if key not in seen:
                with contextlib.suppress(Exception):  # a failed run is recorded, like the job's
                    ingest_file(
                        key,
                        engine=engine,
                        bucket=bucket,
                        contracts=load_contracts(),
                        commit_sha="e2e0000",
                        workdir=workdir,
                    )

    return sleep


def test_samples_cover_every_contract_folder_and_broken_file():
    items = {s.key: s for s in samples()}
    assert items[KEY].contract == "cse-cic-ids2018" and items[KEY].missing == ()
    broken = items["raw/missing-dst-port.csv"]
    assert broken.contract is None and broken.missing == ("dst_port",)


def test_reset_empties_the_tables_and_the_bucket(engine, bucket, tmp_path):
    upload(bucket, samples())
    ingest_on_upload(engine, bucket, tmp_path)(0)
    reset(engine, bucket)
    with engine.connect() as conn:
        counts = [conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one() for t in TABLES]  # noqa: S608
    assert counts == [0] * len(TABLES)
    assert "Contents" not in bucket.client.list_objects_v2(Bucket=bucket.name)


def test_run_passes_when_ingestion_behaves(
    engine, bucket, tmp_path, settings_env, monkeypatch, clear_caches
):
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("S3_BUCKET", bucket.name)
    clear_caches()
    sleep = ingest_on_upload(engine, bucket, tmp_path)
    assert run(engine, bucket, load_contracts(), sleep=sleep) == []


def test_wait_ignores_runs_from_before_the_upload(engine):
    old = start_run(engine, "cse-cic-ids2018", KEY, "old0000")
    finish_run(engine, old, RunRecord(status="loaded", message="old", rows_loaded=5))
    since = db_now(engine)
    assert wait_for_runs(engine, [KEY], since, timeout_s=0, sleep=lambda s: None) == {}


def test_check_names_each_broken_expectation(engine, bucket):
    good = next(s for s in samples() if s.key == KEY)
    broken = next(s for s in samples() if s.key == "raw/missing-dst-port.csv")
    finished = {
        good.key: Finished(good.key, "quarantined", "no contract", 0, "cse-cic-ids2018"),
        broken.key: Finished(broken.key, "loaded", "ok", 10, "missing-dst-port"),
    }
    messages = check([good, broken], finished, load_contracts(), bucket, engine)
    assert any(m.startswith(f"{good.key}: quarantined, expected loaded") for m in messages)
    assert any(m.startswith(f"{broken.key}: loaded, expected quarantined") for m in messages)
    assert check([good], {}, load_contracts(), bucket, engine) == [f"{good.key}: no finished run"]


def test_render_pages_reports_a_page_that_raises(tmp_path, settings_env):
    (tmp_path / "boom.py").write_text("raise RuntimeError('boom')\n")
    messages = render_pages(["cse-cic-ids2018"], views=tmp_path)
    assert messages[0].startswith("boom on cse-cic-ids2018:")

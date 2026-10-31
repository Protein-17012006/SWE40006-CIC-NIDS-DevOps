import json
import random
from pathlib import Path

import pandas as pd
import pytest
import sqlalchemy as sa
import yaml

from pipeline.clean import CHUNK_ROWS
from pipeline.contracts import load_contracts
from pipeline.ingest import ingest_file, reconcile

pytestmark = pytest.mark.db
TESTS = Path(__file__).resolve().parents[1]
WED = TESTS / "contracts/cse-cic-ids2018/wednesday-14-02-2018.csv"
BROKEN = TESTS / "contracts/broken"
EXPECTED = yaml.safe_load((BROKEN / "expected.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def ingest(engine, bucket, tmp_path):
    def run(key, contracts=None, chunk_rows=CHUNK_ROWS):
        return ingest_file(
            key,
            engine=engine,
            bucket=bucket,
            contracts=load_contracts() if contracts is None else contracts,
            commit_sha="abc1234",
            workdir=tmp_path / "work",
            chunk_rows=chunk_rows,
        )

    (tmp_path / "work").mkdir()
    return run


def upload(bucket, path: Path, key: str) -> str:
    bucket.upload(path, key)
    return key


def upload_frame(bucket, tmp_path, frame: pd.DataFrame, key: str) -> str:
    path = tmp_path / f"upload-{random.random():.6f}.csv"
    frame.to_csv(path, index=False)
    return upload(bucket, path, key)


def wed() -> pd.DataFrame:
    return pd.read_csv(WED, dtype=str, keep_default_na=False)


def one(engine, query: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(query), params).mappings().one()


def steps(engine, run_id: int) -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT step, rows_affected FROM quality_steps WHERE run_id = :r"),
            {"r": run_id},
        )
        return dict(rows.all())


def latest_run(engine):
    return one(engine, "SELECT * FROM ingestion_runs ORDER BY run_id DESC LIMIT 1")


def events(capsys, name: str) -> list[dict]:
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    return [line for line in lines if line["event"] == name]


def keys(bucket, prefix: str) -> list[str]:
    page = bucket.client.list_objects_v2(Bucket=bucket.name, Prefix=prefix)
    return sorted(item["Key"] for item in page.get("Contents", []))


def test_ingest_baseline_sample_loads(ingest, bucket, engine, capsys):
    upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv")
    r = ingest("raw/cse-cic-ids2018/wed.csv")
    assert (r.status, r.rows_read, r.contract_name, r.contract_version) == (
        "loaded",
        200,
        "cse-cic-ids2018",
        1,
    )
    assert r.message.startswith(f"Loaded {r.rows_loaded:,} of 200 rows with cse-cic-ids2018 v1.")
    run = latest_run(engine)
    counted = steps(engine, run["run_id"])
    assert r.rows_read == (
        r.rows_loaded
        + r.rows_rejected
        + counted["duplicates_removed"]
        + counted["repeated_headers_dropped"]
    )
    assert (run["status"], run["commit_sha"], run["file_key"]) == (
        "loaded",
        "abc1234",
        "raw/cse-cic-ids2018/wed.csv",
    )
    ds = one(engine, "SELECT * FROM datasets WHERE dataset_id = 'cse-cic-ids2018'")
    assert (ds["status"], ds["row_count"], ds["has_label"]) == ("loaded", r.rows_loaded, True)
    assert "attack_category" in ds["fields"] and "fwd_pkt_len_max" in ds["extra_fields"]
    parts = keys(bucket, "processed/cse-cic-ids2018/wed/")
    assert parts == ["processed/cse-cic-ids2018/wed/part-0000.parquet"]
    event = events(capsys, "ingestion_run")[-1]
    assert (event["status"], event["contract"], event["rows_read"]) == (
        "loaded",
        "cse-cic-ids2018 v1",
        200,
    )
    assert event["duration_s"] >= 0 and event["run_id"] == run["run_id"]


def test_processed_parquet_holds_the_cleaned_rows(ingest, bucket, tmp_path):
    upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv")
    r = ingest("raw/cse-cic-ids2018/wed.csv")
    bucket.download("processed/cse-cic-ids2018/wed/part-0000.parquet", tmp_path / "p.parquet")
    frame = pd.read_parquet(tmp_path / "p.parquet")
    assert len(frame) == r.rows_loaded
    assert {"dst_port", "attack_category", "fwd_pkt_len_max"} <= set(frame.columns)
    assert "Dst Port" not in frame.columns


def test_ingest_columns_in_a_different_order_loads(ingest, bucket, tmp_path):
    upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv")
    plain = ingest("raw/cse-cic-ids2018/wed.csv")
    frame = wed()
    shuffled = frame[random.Random(5).sample(list(frame.columns), len(frame.columns))]
    upload_frame(bucket, tmp_path, shuffled, "raw/cse-cic-ids2018/shuffled.csv")
    r = ingest("raw/cse-cic-ids2018/shuffled.csv")
    assert (r.status, r.rows_loaded) == ("loaded", plain.rows_loaded)


def test_ingest_flags_two_new_columns(ingest, bucket, tmp_path):
    frame = wed().assign(pkt_entropy="3.2", geo_country="VN")
    r = ingest(upload_frame(bucket, tmp_path, frame, "raw/cse-cic-ids2018/extra.csv"))
    assert r.status == "loaded" and r.new_columns == ["pkt_entropy", "geo_country"]
    assert "2 new columns: pkt_entropy, geo_country." in r.message


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_broken_files_are_quarantined_for_the_expected_reason(ingest, bucket, engine, name):
    r = ingest(upload(bucket, BROKEN / name, f"raw/broken/{name}"))
    missing = ", ".join(EXPECTED[name]["missing"])
    assert r.status == "quarantined"
    assert r.message.startswith(f"No contract matches: missing {missing} (closest: ")
    assert bucket.exists(r.report_key) and bucket.exists(r.draft_contract_key)
    assert keys(bucket, "processed/") == []
    assert latest_run(engine)["status"] == "quarantined"
    report = bucket.read_text(r.report_key)
    assert all(field in report for field in EXPECTED[name]["missing"])


def test_ingest_mostly_unknown_labels_quarantined(ingest, bucket, tmp_path):
    frame = wed()
    frame.loc[frame.index[:70], "Label"] = "Worm"
    r = ingest(upload_frame(bucket, tmp_path, frame, "raw/cse-cic-ids2018/worm.csv"))
    assert r.status == "quarantined" and r.message == (
        "35.0% of rows failed validation with cse-cic-ids2018 v1."
    )
    assert (r.rows_rejected, r.contract_name) == (70, "cse-cic-ids2018")
    report = bucket.read_text(r.report_key)
    assert "Worm" in report and "| 70 |" in report and bucket.exists(r.draft_contract_key)
    assert keys(bucket, "processed/") == []


def test_a_few_unknown_labels_are_rejected_and_named(ingest, bucket, tmp_path):
    frame = wed()
    frame.loc[frame.index[:3], "Label"] = "Worm"
    r = ingest(upload_frame(bucket, tmp_path, frame, "raw/cse-cic-ids2018/few.csv"))
    assert r.status == "loaded" and r.rows_rejected == 3
    assert "Rejected 3 rows: unknown label Worm (3)." in r.message


@pytest.mark.parametrize("content", [b"", b"Dst Port,Protocol,Label\n"])
def test_a_file_without_data_rows_is_quarantined(ingest, bucket, tmp_path, content):
    path = tmp_path / "empty.csv"
    path.write_bytes(content if content else b"")
    if content:  # a header the baseline contract matches, but no rows
        path.write_text(",".join(pd.read_csv(WED, nrows=0).columns) + "\n")
    r = ingest(upload(bucket, path, "raw/cse-cic-ids2018/empty.csv"))
    assert (r.status, r.message) == ("quarantined", "The file has no data rows.")
    assert bucket.exists(r.report_key)


def test_ingest_twice_replaces_rows(ingest, bucket, engine):
    upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv")
    first = ingest("raw/cse-cic-ids2018/wed.csv")
    ingest("raw/cse-cic-ids2018/wed.csv")
    ds = one(engine, "SELECT row_count FROM datasets WHERE dataset_id = 'cse-cic-ids2018'")
    sample = one(engine, "SELECT count(*) AS n FROM flow_sample")
    runs = one(engine, "SELECT count(*) AS n FROM ingestion_runs")
    assert (ds["row_count"], sample["n"], runs["n"]) == (first.rows_loaded, first.rows_loaded, 2)


def test_reingest_deletes_stale_parts(ingest, bucket):
    upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv")
    ingest("raw/cse-cic-ids2018/wed.csv", chunk_rows=50)
    assert len(keys(bucket, "processed/cse-cic-ids2018/wed/")) == 4
    ingest("raw/cse-cic-ids2018/wed.csv")
    assert keys(bucket, "processed/cse-cic-ids2018/wed/") == [
        "processed/cse-cic-ids2018/wed/part-0000.parquet"
    ]


def test_ingest_resolves_an_encoded_event_key(ingest, bucket, engine):
    upload(bucket, WED, "raw/my capture.csv")
    r = ingest("raw/my+capture.csv")
    assert r.status == "loaded"
    run = latest_run(engine)
    assert (run["file_key"], run["dataset_id"]) == ("raw/my capture.csv", "my-capture")


def test_ingest_failure_marks_run_failed_and_raises(ingest, bucket, engine, monkeypatch, capsys):
    upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv")

    def broken_download(key, path):
        raise OSError("disk full\nsecond line")

    monkeypatch.setattr(bucket, "download", broken_download)
    with pytest.raises(OSError, match="disk full"):
        ingest("raw/cse-cic-ids2018/wed.csv")
    run = latest_run(engine)
    assert (run["status"], run["message"]) == ("failed", "Failed: OSError: disk full")
    event = events(capsys, "ingestion_run")[-1]
    assert (event["level"], event["status"]) == ("ERROR", "failed")


def test_a_missing_object_records_no_run(ingest, engine):
    with pytest.raises(FileNotFoundError):
        ingest("raw/cse-cic-ids2018/gone.csv")
    assert one(engine, "SELECT count(*) AS n FROM ingestion_runs")["n"] == 0


# Reconcile (ING-09) and status

SIM_KEY = "raw/simulated-real-traffic-01.csv"


def simulated_contract():
    return load_contracts(TESTS / "fixtures/contracts")[0]


def baseline(version: int = 1):
    contract = next(c for c in load_contracts() if c.name == "cse-cic-ids2018")
    return contract.model_copy(update={"version": version})


@pytest.fixture
def reconcile_with(engine, bucket, tmp_path):
    def run(contracts):
        return reconcile(
            engine=engine,
            bucket=bucket,
            contracts=contracts,
            commit_sha="def5678",
            workdir=tmp_path / "work",
        )

    return run


def dataset_row(engine, dataset_id: str):
    return one(engine, "SELECT * FROM datasets WHERE dataset_id = :d", d=dataset_id)


def test_reconcile_loads_a_quarantined_file_once_its_contract_exists(
    ingest, reconcile_with, bucket, engine, simulated_csv
):
    upload(bucket, simulated_csv, SIM_KEY)
    assert ingest(SIM_KEY, contracts=[baseline()]).status == "quarantined"
    s = reconcile_with([baseline(), simulated_contract()])
    assert (s.reingested, s.missing, s.failed) == ([SIM_KEY], [], [])
    ds = dataset_row(engine, "simulated-real-traffic-01")
    assert (ds["status"], ds["has_label"], ds["contract_name"]) == (
        "loaded",
        False,
        "simulated-real-traffic",
    )
    assert "pkt_entropy" in ds["extra_fields"] and latest_run(engine)["commit_sha"] == "def5678"


def test_reconcile_reingests_after_a_version_bump_and_then_stops(ingest, reconcile_with, bucket):
    ingest(upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv"))
    assert reconcile_with([baseline(1)]).reingested == []
    assert reconcile_with([baseline(2)]).reingested == ["raw/cse-cic-ids2018/wed.csv"]
    assert reconcile_with([baseline(2)]).reingested == []


def test_reconcile_skips_quarantine_with_same_contract(ingest, reconcile_with, bucket, tmp_path):
    frame = wed()
    frame.loc[frame.index[:70], "Label"] = "Worm"
    ingest(upload_frame(bucket, tmp_path, frame, "raw/cse-cic-ids2018/worm.csv"))
    s = reconcile_with(load_contracts())
    assert (s.reingested, s.skipped) == ([], 1)


def test_reconcile_skips_when_contract_is_gone(ingest, reconcile_with, bucket, simulated_csv):
    upload(bucket, simulated_csv, SIM_KEY)
    assert ingest(SIM_KEY, contracts=[baseline(), simulated_contract()]).status == "loaded"
    assert reconcile_with([baseline()]).reingested == []


def test_reconcile_skips_missing_raw_object(ingest, reconcile_with, bucket, simulated_csv):
    ingest(upload(bucket, simulated_csv, SIM_KEY), contracts=[baseline()])
    bucket.client.delete_object(Bucket=bucket.name, Key=SIM_KEY)
    s = reconcile_with([baseline(), simulated_contract()])
    assert (s.reingested, s.missing) == ([], [SIM_KEY])


def test_reconcile_fails_stale_running_runs(reconcile_with, engine):
    from pipeline.load import start_run

    run = start_run(engine, "d", "raw/d/a.csv", "abc1234")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE ingestion_runs SET started_at = now() - interval '3 hours' "
                "WHERE run_id = :r"
            ),
            {"r": run},
        )
    s = reconcile_with(load_contracts())
    assert (s.stale_failed, s.reingested) == (1, [])
    assert latest_run(engine)["status"] == "failed"


def test_reconcile_keeps_going_after_a_failed_reingest(
    ingest, reconcile_with, bucket, monkeypatch, simulated_csv
):
    first, second = "raw/sim-a.csv", "raw/sim-b.csv"
    ingest(upload(bucket, simulated_csv, first), contracts=[baseline()])
    ingest(upload(bucket, simulated_csv, second), contracts=[baseline()])
    download = bucket.download

    def flaky(key, path):
        if key == first:
            raise OSError("network down")
        download(key, path)

    monkeypatch.setattr(bucket, "download", flaky)
    s = reconcile_with([baseline(), simulated_contract()])
    assert (s.failed, s.reingested) == ([first], [second])


def _cli_env(monkeypatch, settings_env, migrated_db_url):
    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    monkeypatch.setenv("S3_BUCKET", "cicnids-test")
    get_settings.cache_clear()


def test_cli_status_logs_each_dataset(
    ingest, bucket, monkeypatch, settings_env, migrated_db_url, capsys
):
    from pipeline.cli import main

    ingest(upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv"))
    _cli_env(monkeypatch, settings_env, migrated_db_url)
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr()
    statuses = [json.loads(line) for line in out.out.splitlines()]
    datasets = [e for e in statuses if e["event"] == "dataset_status"]
    assert [(d["dataset_id"], d["status"], d["files"]) for d in datasets] == [
        ("cse-cic-ids2018", "loaded", 1)
    ]
    sizes = next(e for e in statuses if e["event"] == "table_sizes")
    assert sizes["flow_sample"] > 0
    assert statuses[-1]["message"] == "1 datasets"


def test_cli_reconcile_and_ingest(bucket, monkeypatch, settings_env, migrated_db_url, capsys):
    from pipeline.cli import main

    upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv")
    _cli_env(monkeypatch, settings_env, migrated_db_url)
    assert main(["ingest", "--key", "raw/cse-cic-ids2018/wed.csv"]) == 0
    assert main(["reconcile"]) == 0
    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (last["event"], last["status"]) == ("reconcile", "ok")
    assert last["message"].startswith("re-ingested 0 files")

import pytest
import sqlalchemy as sa

from app.data.db import make_engine, ping
from app.data.queries import last_ingestion_run, loaded_datasets


def _insert_runs(url: str, count: int) -> None:
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            for _ in range(count):
                conn.execute(
                    sa.text(
                        "INSERT INTO ingestion_runs (dataset_id, file_key, commit_sha, status) "
                        "VALUES ('d', 'raw/f.csv', 'abc1234', 'loaded')"
                    )
                )
    finally:
        engine.dispose()


@pytest.mark.db
def test_ping_reports_version_and_latency(migrated_db_url):
    engine = make_engine(migrated_db_url)
    try:
        result = ping(engine)
    finally:
        engine.dispose()
    assert result.ok and result.server_version.startswith("16.") and result.latency_ms >= 0


@pytest.mark.db
def test_last_ingestion_run_is_empty_then_latest(
    migrated_db_url, settings_env, monkeypatch, clear_caches
):
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    clear_caches()
    assert last_ingestion_run().empty
    _insert_runs(migrated_db_url, count=2)
    clear_caches()
    assert last_ingestion_run()["run_id"].tolist() == [2]


@pytest.mark.db
def test_loaded_datasets_baseline_first(use_seeded_db):
    datasets = loaded_datasets()
    assert datasets["dataset_id"].tolist() == ["cse-cic-ids2018", "simulated-real-traffic-01"]
    assert datasets["extra_fields"].tolist() == [
        ["bwd_psh_flags", "fwd_pkt_len_max"],
        ["pkt_entropy", "geo_country"],
    ]

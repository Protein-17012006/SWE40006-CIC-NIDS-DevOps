import pytest
import sqlalchemy as sa

from app.data.db import make_engine, ping
from app.data.queries import last_ingestion_run


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

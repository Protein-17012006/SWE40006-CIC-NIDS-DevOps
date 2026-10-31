from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PIPELINE_PAGE = str(Path(__file__).resolve().parents[2] / "app" / "views" / "pipeline.py")


def test_tiles_with_unreachable_database(settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    clear_caches()
    at = AppTest.from_file(PIPELINE_PAGE, default_timeout=30).run()
    tiles = {m.label: m.value for m in at.metric}
    assert not at.exception
    assert tiles == {
        "Environment": "test",
        "App version": "abc1234",
        "Database": "Unreachable",
        "Last ingestion": "—",
    }


@pytest.mark.db
def test_tiles_with_migrated_database(settings_env, migrated_db_url, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    clear_caches()
    at = AppTest.from_file(PIPELINE_PAGE, default_timeout=30).run()
    tiles = {m.label: m.value for m in at.metric}
    assert tiles["Database"] == "Connected" and tiles["Last ingestion"] == "—"

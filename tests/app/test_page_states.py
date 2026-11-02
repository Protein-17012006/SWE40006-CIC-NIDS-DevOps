"""Every page that reads the filters, in the two states with nothing to show."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.components.filters import DB_DOWN, NO_DATA

APP = Path(__file__).resolve().parents[2] / "app"
PAGES = [
    "overview",
    "timeline",
    "targets",
    "data_quality",
    "feature_explorer",
]  # each page's pull request adds its view


def _run(page: str) -> AppTest:
    return AppTest.from_file(str(APP / "views" / f"{page}.py"), default_timeout=30).run()


@pytest.mark.parametrize("page", PAGES)
def test_page_without_database(page, settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    clear_caches()
    at = _run(page)
    assert not at.exception and at.error[0].value == DB_DOWN


@pytest.mark.db
@pytest.mark.parametrize("page", PAGES)
def test_page_on_an_empty_database(page, migrated_db_url, settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    clear_caches()
    at = _run(page)
    assert not at.exception and at.info[0].value == NO_DATA

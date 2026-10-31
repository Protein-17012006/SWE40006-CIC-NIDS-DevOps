import os
import uuid

import pytest
import sqlalchemy as sa


@pytest.fixture
def settings_env(monkeypatch):
    """Settings for a test environment with no database and no bucket."""
    from app.config import get_settings

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_VERSION", "abc1234")
    for name in ("DATABASE_URL", "DB_SECRET", "S3_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _clear_caches() -> None:
    import streamlit as st

    from app.config import get_settings

    get_settings.cache_clear()
    st.cache_data.clear()
    st.cache_resource.clear()


@pytest.fixture
def clear_caches():
    """Gives the test a function that resets settings and Streamlit caches; runs again after it."""
    _clear_caches()
    yield _clear_caches
    _clear_caches()


@pytest.fixture(scope="session")
def admin_url():
    """Superuser URL that creates and drops the per-test databases; skips db tests without it."""
    url = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("TEST_ADMIN_DATABASE_URL is not set")
    return url


@pytest.fixture
def empty_db_url(admin_url):
    name = f"cicnids_t_{uuid.uuid4().hex[:8]}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = sa.make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def migrated_db_url(empty_db_url):
    from pipeline.migrate import upgrade

    upgrade(empty_db_url)
    return empty_db_url


@pytest.fixture
def engine(migrated_db_url):
    """An engine on a freshly migrated test database."""
    engine = sa.create_engine(migrated_db_url)
    yield engine
    engine.dispose()

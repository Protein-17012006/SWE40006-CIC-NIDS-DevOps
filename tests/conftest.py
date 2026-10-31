import pytest


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

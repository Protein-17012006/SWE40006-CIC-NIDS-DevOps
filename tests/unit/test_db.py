import time

from app.data.db import PingResult, make_engine, ping


def test_ping_without_engine_reports_not_configured():
    assert ping(None) == PingResult(False, None, None, "DATABASE_URL is not set")


def test_ping_unreachable_database_fails_fast():
    started = time.monotonic()
    result = ping(make_engine("postgresql+psycopg://u:secret-pw@127.0.0.1:1/db"))
    assert result.ok is False and result.latency_ms is None
    assert time.monotonic() - started < 5
    assert "secret-pw" not in (result.error or "")

import json

import pytest

from app.telemetry import log_event, page_render


def test_log_event_prints_one_json_line(capsys, settings_env):
    log_event("ingestion_run", status="loaded", rows_read=10)
    lines = capsys.readouterr().out.strip().splitlines()
    rec = json.loads(lines[0])
    assert len(lines) == 1 and rec["event"] == "ingestion_run" and rec["level"] == "INFO"
    assert (rec["env"], rec["version"], rec["status"], rec["rows_read"]) == (
        "test",
        "abc1234",
        "loaded",
        10,
    )
    assert rec["ts"].endswith("Z")


def test_log_event_drops_sensitive_fields(capsys, settings_env):
    log_event(
        "debug",
        password="x",
        database_url="postgresql://u:p@h/d",
        DB_SECRET="{}",
        page="overview",
    )
    rec = json.loads(capsys.readouterr().out)
    assert {"password", "database_url", "DB_SECRET"}.isdisjoint(rec) and rec["page"] == "overview"


def test_page_render_logs_duration(capsys, settings_env):
    with page_render("pipeline"):
        pass
    rec = json.loads(capsys.readouterr().out)
    assert (rec["event"], rec["page"]) == ("page_render", "pipeline")
    assert isinstance(rec["duration_ms"], int) and rec["duration_ms"] >= 0


def test_page_render_logs_error_and_reraises(capsys, settings_env):
    with pytest.raises(RuntimeError):
        with page_render("overview"):
            raise RuntimeError("boom")
    assert json.loads(capsys.readouterr().out)["level"] == "ERROR"

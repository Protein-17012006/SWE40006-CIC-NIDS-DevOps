"""Pipeline page (Figma frame 06): what runs here and whether it can reach its database."""

import pandas as pd
import streamlit as st

from app.components.layout import kpi_tile, page_header
from app.config import get_settings
from app.data.db import get_engine, ping
from app.data.queries import last_ingestion_run
from app.telemetry import log_event

settings = get_settings()
page_header(
    "Pipeline",
    "Datasets, ingestion runs and the version running here. This page ignores the sidebar filters.",
)

if settings.app_env == "local":
    where = "laptop · docker compose"
else:
    where = f"{settings.aws_region} · ECS on Fargate"

db = ping(get_engine())
if db.ok:
    engine_name = "PostgreSQL" if settings.app_env == "local" else "RDS PostgreSQL"
    db_value, db_caption = "Connected", f"{engine_name} {db.server_version} · {db.latency_ms} ms"
else:
    db_value, db_caption = "Unreachable", db.error or "no connection"

try:
    runs = last_ingestion_run()
except Exception as exc:  # before the first migration, or while the database is down
    first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    log_event("query_failed", level="ERROR", query="last_ingestion_run", message=first_line)
    run_value, run_caption = "—", "runs table not available"
else:
    if runs.empty:
        run_value, run_caption = "—", "no runs yet"
    else:
        latest = runs.iloc[0]
        started = pd.Timestamp(latest["started_at"]).tz_convert("UTC")
        run_value, run_caption = f"#{latest['run_id']}", f"started {started:%Y-%m-%d %H:%M} UTC"

tiles = [
    ("Environment", settings.app_env, where),
    ("App version", settings.app_version, f"started {settings.started_at:%Y-%m-%d %H:%M} UTC"),
    ("Database", db_value, db_caption),
    ("Last ingestion", run_value, run_caption),
]
for column, (label, value, caption) in zip(st.columns(4), tiles, strict=True):
    with column:
        kpi_tile(label, value, caption)

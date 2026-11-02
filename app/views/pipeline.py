"""Pipeline page (UI-07, Figma frame 06): what runs here, which datasets are loaded under which
contract, and which files were quarantined. It covers the whole environment, so no filters."""

import pandas as pd
import streamlit as st

from app.components.format import basename, compact, mmss, plural, stamp_label
from app.components.layout import chart_card, kpi_tile, page_header
from app.config import get_settings
from app.data import queries, storage
from app.data.db import get_engine, ping
from app.data.queries import last_ingestion_run
from app.telemetry import log_event

STATUS = {
    "loaded": "✅ Loaded",
    "quarantined": "⚠️ Quarantined",
    "failed": "❌ Failed",
    "running": "⏳ Running",
}
LOADS_ON_DEPLOY = (
    "Once a contract for this file is merged and deployed, the deployment loads the file."
)


def utc(ts: object) -> str:
    if pd.isna(ts):
        return "—"
    stamp = pd.Timestamp(ts)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp_label(stamp)


def datasets_view(df: pd.DataFrame) -> None:
    contracts = [
        f"{name} v{int(version)}" if pd.notna(name) else "no match"
        for name, version in zip(df["contract_name"], df["contract_version"], strict=True)
    ]
    table = pd.DataFrame(
        {
            "Dataset": [
                f"{name} ({plural(int(files), 'file')})"
                for name, files in zip(df["display_name"], df["files"], strict=True)
            ],
            "Contract": contracts,
            "Rows": df["row_count"].map(compact),
            "Last run": df["last_run_at"].map(utc),
            "Status": df["status"].map(STATUS),
        }
    )
    st.dataframe(table, hide_index=True)


def runs_view(df: pd.DataFrame) -> None:
    durations = [
        "—" if pd.isna(end) else mmss((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds())
        for start, end in zip(df["started_at"], df["ended_at"], strict=True)
    ]
    table = pd.DataFrame(
        {
            "Run": df["run_id"].map(lambda run: f"#{run}"),
            "File": df["file_key"].map(basename),
            "Started": df["started_at"].map(utc),
            "Duration": durations,
            "Loaded": df["rows_loaded"].map(lambda n: f"{n:,}"),
            "Rejected": df["rows_rejected"].map(lambda n: f"{n:,}"),
            "Status": df["status"].map(STATUS),
        }
    )
    st.dataframe(table, hide_index=True)


@st.dialog("Quarantine report", width="large")
def show_report(key: str | None) -> None:
    text = storage.read_text(key) if key else None
    if text is None:
        st.warning("The report could not be read.")
    else:
        st.markdown(text)


def object_key(value: object) -> str | None:
    """A stored S3 key, or None; pandas 3 reads a missing text value as NaN, which is truthy."""
    return value if isinstance(value, str) and value else None


def quarantine_view(df: pd.DataFrame) -> None:
    for row in df.itertuples(index=False):
        st.warning(f"**{basename(row.file_key)}** · run #{row.run_id}\n\n{row.message}")
        report_key, draft_key = object_key(row.report_key), object_key(row.draft_contract_key)
        # A file quarantined for too many rejected rows has no report or draft to offer
        if storage.has_bucket() and (report_key or draft_key):
            draft = storage.read_text(draft_key) if draft_key else None
            with st.container(horizontal=True):
                if report_key and st.button(
                    "View report", key=f"report-{row.run_id}", icon=":material/description:"
                ):
                    show_report(report_key)
                if draft is not None:
                    st.download_button(
                        "Download draft contract",
                        draft,
                        file_name="draft-contract.yaml",
                        mime="application/yaml",
                        key=f"draft-{row.run_id}",
                        icon=":material/download:",
                    )
            if draft_key and draft is None:
                st.caption("The draft contract could not be read.")
        st.caption(LOADS_ON_DEPLOY)


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

chart_card(
    "Datasets",
    "One row per source; a contract maps each source to the canonical fields",
    queries.datasets_table,
    datasets_view,
    empty="No dataset has been ingested yet.",
)
chart_card(
    "Recent ingestion runs",
    "Newest first",
    queries.recent_runs,
    runs_view,
    empty="No ingestion has run yet.",
)
chart_card(
    "Quarantined files",
    "Files that did not match any data contract",
    queries.quarantined_files,
    quarantine_view,
    csv=False,
    empty="No file is quarantined.",
)

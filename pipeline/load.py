"""Run records and the one transaction that loads a file's results (ING-05, ING-06).

finish_run holds an advisory lock on the dataset, so two runs of the same dataset never
interleave their deletes and inserts, and a re-ingested file replaces only its own rows.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.data.fields import CANONICAL_FIELDS
from pipeline.accumulate import SAMPLE_COLUMNS, ColumnIssue

TABLES = (
    "datasets",
    "ingestion_runs",
    "quality_steps",
    "quality_columns",
    "agg_hourly",
    "agg_ports",
    "flow_sample",
)
STALE_MESSAGE = "Failed: the task stopped before the run finished."
_FIELD_ORDER = [f.name for f in CANONICAL_FIELDS]
_FIELD_ORDER.insert(_FIELD_ORDER.index("label") + 1, "attack_category")

# The dataset row is recomputed from what is stored: aggregates for the counts, and the latest
# loaded run of each file for the time span and the contract
_DATASET_TOTALS = """
WITH latest AS (
    SELECT DISTINCT ON (file_key) run_id, contract_name, contract_version,
           first_ts, last_ts, ended_at
    FROM ingestion_runs WHERE dataset_id = :d AND status = 'loaded'
    ORDER BY file_key, run_id DESC
)
SELECT
    (SELECT COALESCE(SUM(flows), 0) FROM agg_hourly WHERE dataset_id = :d) AS row_count,
    EXISTS (SELECT 1 FROM agg_hourly WHERE dataset_id = :d) AS has_rows,
    (SELECT MIN(first_ts) FROM latest) AS first_ts,
    (SELECT MAX(last_ts) FROM latest) AS last_ts,
    (SELECT contract_name FROM latest ORDER BY run_id DESC LIMIT 1) AS contract_name,
    (SELECT contract_version FROM latest ORDER BY run_id DESC LIMIT 1) AS contract_version,
    (SELECT ended_at FROM latest ORDER BY run_id DESC LIMIT 1) AS loaded_at
"""

_agg_hourly = sa.table(
    "agg_hourly",
    *(sa.column(c) for c in ("dataset_id", "file_key", "hour", "label", "attack_category")),
    sa.column("flows"),
)
_agg_ports = sa.table(
    "agg_ports",
    *(sa.column(c) for c in ("dataset_id", "file_key", "day", "attack_category", "protocol")),
    sa.column("dst_port"),
    sa.column("flows"),
)
_flow_sample = sa.table(
    "flow_sample",
    sa.column("dataset_id"),
    sa.column("file_key"),
    *(sa.column(c) for c in SAMPLE_COLUMNS),
    sa.column("extras", JSONB),
)
_quality_steps = sa.table(
    "quality_steps", sa.column("run_id"), sa.column("step"), sa.column("rows_affected")
)
_quality_columns = sa.table(
    "quality_columns",
    *(sa.column(c) for c in ("run_id", "column_name", "nulls", "infinite", "action")),
)


@dataclass
class RunRecord:
    status: str
    message: str
    contract_name: str | None = None
    contract_version: int | None = None
    rows_read: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    source_columns: list[str] = field(default_factory=list)
    new_columns: list[str] = field(default_factory=list)
    report_key: str | None = None
    draft_contract_key: str | None = None
    first_ts: datetime | None = None
    last_ts: datetime | None = None


@dataclass
class FileData:
    hourly: pd.DataFrame
    ports: pd.DataFrame
    sample: pd.DataFrame
    steps: dict[str, int]
    columns: list[ColumnIssue]
    fields: list[str]
    extra_fields: list[str]
    has_label: bool


@dataclass(frozen=True)
class LatestRun:
    run_id: int
    dataset_id: str
    file_key: str
    status: str
    contract_name: str | None
    contract_version: int | None
    source_columns: list[str]


def _plain(value: object) -> object:
    """A value psycopg can bind: None for every kind of missing, Python scalars for numpy."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _records(frame: pd.DataFrame, **constants: object) -> list[dict[str, object]]:
    columns = list(frame.columns)
    return [
        {**constants, **{c: _plain(v) for c, v in zip(columns, row, strict=True)}}
        for row in frame.itertuples(index=False, name=None)
    ]


def start_run(engine: sa.Engine, dataset_id: str, file_key: str, commit_sha: str) -> int:
    with engine.begin() as conn:
        return conn.execute(
            sa.text(
                "INSERT INTO ingestion_runs (dataset_id, file_key, commit_sha, status) "
                "VALUES (:dataset_id, :file_key, :commit_sha, 'running') RETURNING run_id"
            ),
            {"dataset_id": dataset_id, "file_key": file_key, "commit_sha": commit_sha},
        ).scalar_one()


def finish_run(
    engine: sa.Engine, run_id: int, record: RunRecord, data: FileData | None = None
) -> None:
    with engine.begin() as conn:
        dataset_id, file_key = conn.execute(
            sa.text("SELECT dataset_id, file_key FROM ingestion_runs WHERE run_id = :r"),
            {"r": run_id},
        ).one()
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:d))"), {"d": dataset_id})
        if data is not None:
            _replace_file_rows(conn, run_id, dataset_id, file_key, data)
        _update_run(conn, run_id, record)
        if record.status in ("loaded", "quarantined"):
            _upsert_dataset(conn, dataset_id, data)


def _replace_file_rows(
    conn: sa.Connection, run_id: int, dataset_id: str, file_key: str, data: FileData
) -> None:
    keys = {"dataset_id": dataset_id, "file_key": file_key}
    for table in (_agg_hourly, _agg_ports, _flow_sample):
        conn.execute(
            table.delete().where(table.c.dataset_id == dataset_id, table.c.file_key == file_key)
        )
    for table, frame in ((_agg_hourly, data.hourly), (_agg_ports, data.ports)):
        if len(frame):
            conn.execute(table.insert(), _records(frame, **keys))
    if len(data.sample):
        conn.execute(_flow_sample.insert(), _records(data.sample, **keys))
    steps = [{"run_id": run_id, "step": s, "rows_affected": n} for s, n in data.steps.items()]
    if steps:
        conn.execute(_quality_steps.insert(), steps)
    issues = [
        {
            "run_id": run_id,
            "column_name": c.column_name,
            "nulls": c.nulls,
            "infinite": c.infinite,
            "action": c.action,
        }
        for c in data.columns
    ]
    if issues:
        conn.execute(_quality_columns.insert(), issues)


def _update_run(conn: sa.Connection, run_id: int, record: RunRecord) -> None:
    conn.execute(
        sa.text(
            "UPDATE ingestion_runs SET status = :status, message = :message, "
            "contract_name = :contract_name, contract_version = :contract_version, "
            "rows_read = :rows_read, rows_loaded = :rows_loaded, rows_rejected = :rows_rejected, "
            "source_columns = :source_columns, new_columns = :new_columns, "
            "report_key = :report_key, draft_contract_key = :draft_contract_key, "
            "first_ts = :first_ts, last_ts = :last_ts, ended_at = now() "
            "WHERE run_id = :run_id"
        ).bindparams(
            sa.bindparam("source_columns", type_=ARRAY(sa.Text())),
            sa.bindparam("new_columns", type_=ARRAY(sa.Text())),
        ),
        {
            "run_id": run_id,
            "status": record.status,
            "message": record.message,
            "contract_name": record.contract_name,
            "contract_version": record.contract_version,
            "rows_read": record.rows_read,
            "rows_loaded": record.rows_loaded,
            "rows_rejected": record.rows_rejected,
            "source_columns": list(record.source_columns),
            "new_columns": list(record.new_columns),
            "report_key": record.report_key,
            "draft_contract_key": record.draft_contract_key,
            "first_ts": _plain(record.first_ts),
            "last_ts": _plain(record.last_ts),
        },
    )


def _upsert_dataset(conn: sa.Connection, dataset_id: str, data: FileData | None) -> None:
    """Recompute the dataset row from its stored aggregates and its latest loaded runs."""
    stored = (
        conn.execute(
            sa.text("SELECT fields, extra_fields, has_label FROM datasets WHERE dataset_id = :d"),
            {"d": dataset_id},
        )
        .mappings()
        .one_or_none()
    )
    fields = set(stored["fields"]) if stored else set()
    extra_fields = list(stored["extra_fields"]) if stored else []
    has_label = bool(stored["has_label"]) if stored else False
    if data is not None:
        fields |= set(data.fields)
        extra_fields += [c for c in data.extra_fields if c not in extra_fields]
        has_label = has_label or data.has_label

    totals = (
        conn.execute(
            sa.text(_DATASET_TOTALS),
            {"d": dataset_id},
        )
        .mappings()
        .one()
    )

    statement = sa.text(
        "INSERT INTO datasets (dataset_id, display_name, contract_name, contract_version, "
        "  status, has_label, fields, extra_fields, row_count, first_ts, last_ts, loaded_at) "
        "VALUES (:d, :d, :contract_name, :contract_version, :status, :has_label, :fields, "
        "  :extra_fields, :row_count, :first_ts, :last_ts, :loaded_at) "
        "ON CONFLICT (dataset_id) DO UPDATE SET contract_name = EXCLUDED.contract_name, "
        "  contract_version = EXCLUDED.contract_version, status = EXCLUDED.status, "
        "  has_label = EXCLUDED.has_label, fields = EXCLUDED.fields, "
        "  extra_fields = EXCLUDED.extra_fields, row_count = EXCLUDED.row_count, "
        "  first_ts = EXCLUDED.first_ts, last_ts = EXCLUDED.last_ts, "
        "  loaded_at = EXCLUDED.loaded_at"
    ).bindparams(
        sa.bindparam("fields", type_=ARRAY(sa.Text())),
        sa.bindparam("extra_fields", type_=ARRAY(sa.Text())),
    )
    conn.execute(
        statement,
        {
            "d": dataset_id,
            "contract_name": totals["contract_name"],
            "contract_version": totals["contract_version"],
            "status": "loaded" if totals["has_rows"] else "quarantined",
            "has_label": has_label,
            "fields": [f for f in _FIELD_ORDER if f in fields],
            "extra_fields": extra_fields,
            "row_count": totals["row_count"],
            "first_ts": totals["first_ts"],
            "last_ts": totals["last_ts"],
            "loaded_at": totals["loaded_at"],
        },
    )


def latest_runs(engine: sa.Engine) -> list[LatestRun]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT DISTINCT ON (file_key) run_id, dataset_id, file_key, status, "
                "contract_name, contract_version, source_columns "
                "FROM ingestion_runs ORDER BY file_key, run_id DESC"
            )
        ).mappings()
        return [LatestRun(**{**row, "source_columns": list(row["source_columns"])}) for row in rows]


def mark_stale_runs(engine: sa.Engine, older_than: timedelta = timedelta(hours=2)) -> int:
    """Runs still 'running' long after they started belong to a task that died."""
    with engine.begin() as conn:
        result = conn.execute(
            sa.text(
                "UPDATE ingestion_runs SET status = 'failed', message = :message, "
                "ended_at = now() WHERE status = 'running' AND started_at < now() - :age"
            ),
            {"message": STALE_MESSAGE, "age": older_than},
        )
        return result.rowcount


def dataset_summary(engine: sa.Engine) -> list[dict[str, object]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT d.dataset_id, d.status, "
                "  CASE WHEN d.contract_name IS NULL THEN NULL "
                "       ELSE d.contract_name || ' v' || d.contract_version END AS contract, "
                "  d.row_count, "
                "  (SELECT count(DISTINCT file_key) FROM ingestion_runs r "
                "   WHERE r.dataset_id = d.dataset_id) AS files "
                "FROM datasets d ORDER BY d.dataset_id"
            )
        ).mappings()
        return [dict(row) for row in rows]


def table_sizes(engine: sa.Engine) -> dict[str, int]:
    """Bytes on disk per table, indexes and TOAST included."""
    with engine.connect() as conn:
        return {
            table: conn.execute(
                sa.text("SELECT pg_total_relation_size(CAST(:t AS regclass))"), {"t": table}
            ).scalar_one()
            for table in TABLES
        }

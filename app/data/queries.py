"""One query function per visual. Each returns a DataFrame and is cached for five minutes.

Every query follows report section 4.4: filters are bound parameters, Benign is always kept,
rows without a time are kept, and the category filter applies only to labelled datasets.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
import sqlalchemy as sa
import streamlit as st

from app.data.db import get_engine
from app.data.fields import ATTACK_CATEGORIES, NUMERIC_FIELDS, QUALITY_STEPS
from app.data.ports import protocol_name

if TYPE_CHECKING:  # filters imports this module
    from app.components.filters import Filters

# The CSE-CIC-IDS2018 baseline leads the Dataset filter
BASELINE = "cse-cic-ids2018"


def _read(query: str, **params: object) -> pd.DataFrame:
    engine = get_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is not set")
    with engine.connect() as conn:
        return pd.read_sql_query(sa.text(query), conn, params=params)


def _scope(f: Filters, *, time: str = "hour", categories: bool = True) -> tuple[str, dict]:
    """The WHERE clause and parameters that apply the viewer's filters to one table.

    time names the table's time column: a timestamp (hour, ts) or a date (day).
    """
    clauses = ["dataset_id = :dataset_id"]
    params: dict[str, object] = {"dataset_id": f.dataset_id}
    if f.date_from is not None:
        upper = f"{time} <= :date_to" if time == "day" else f"{time} < :date_to + INTERVAL '1 day'"
        clauses.append(f"({time} IS NULL OR ({time} >= :date_from AND {upper}))")
        params.update(date_from=f.date_from, date_to=f.date_to)
    if categories and f.has_label:
        clauses.append("(attack_category = 'Benign' OR attack_category = ANY(:categories))")
        params["categories"] = list(f.categories)
    return " AND ".join(clauses), params


def _scoped(
    template: str,
    f: Filters,
    *,
    time: str = "hour",
    categories: bool = True,
    fragments: dict[str, str] | None = None,
    **params: object,
) -> pd.DataFrame:
    """Run a query whose {where} placeholder takes the viewer's filters (see _scope).

    The clause, and any fragments, are built only from constants and whitelisted column names
    in this module; every value is a bound parameter.
    """
    where, scope_params = _scope(f, time=time, categories=categories)
    sql = template.format(where=where, **(fragments or {}))
    return _read(sql, **scope_params, **params)


@st.cache_data(ttl=300)
def last_ingestion_run() -> pd.DataFrame:
    return _read("SELECT run_id, started_at FROM ingestion_runs ORDER BY run_id DESC LIMIT 1")


@st.cache_data(ttl=300)
def loaded_datasets() -> pd.DataFrame:
    """Datasets with loaded rows for the Dataset filter, the baseline first, then the largest."""
    return _read(
        "SELECT dataset_id, display_name, has_label, fields, extra_fields, row_count, "
        "first_ts, last_ts, loaded_at FROM datasets WHERE status = 'loaded' "
        "ORDER BY dataset_id = :baseline DESC, row_count DESC, dataset_id",
        baseline=BASELINE,
    )


@st.cache_data(ttl=300)
def dataset_files(dataset_id: str) -> pd.DataFrame:
    """The latest run of each file in a dataset, whatever its status."""
    return _read(
        "SELECT DISTINCT ON (file_key) run_id, file_key, status, rows_read, rows_loaded, "
        "rows_rejected, source_columns, new_columns, started_at FROM ingestion_runs "
        "WHERE dataset_id = :dataset_id ORDER BY file_key, run_id DESC",
        dataset_id=dataset_id,
    )


# Overview (UI-02)


@st.cache_data(ttl=300)
def kpi_totals(f: Filters) -> pd.DataFrame:
    return _scoped(
        "SELECT COALESCE(SUM(flows), 0)::bigint AS flows, "
        "COALESCE(SUM(flows) FILTER (WHERE attack_category <> 'Benign'), 0)::bigint "
        "AS attack_flows, "
        "COUNT(DISTINCT label) FILTER (WHERE attack_category <> 'Benign') AS attack_types, "
        "COUNT(DISTINCT attack_category) FILTER (WHERE attack_category <> 'Benign') "
        "AS categories, "
        "COUNT(DISTINCT hour::date) AS capture_days, "
        "MIN(hour)::date AS first_day, MAX(hour)::date AS last_day "
        "FROM agg_hourly WHERE {where}",
        f,
    )


@st.cache_data(ttl=300)
def flows_by_category(f: Filters) -> pd.DataFrame:
    return _scoped(
        "SELECT attack_category, SUM(flows)::bigint AS flows FROM agg_hourly "
        "WHERE {where} GROUP BY attack_category ORDER BY flows DESC, attack_category",
        f,
    )


@st.cache_data(ttl=300)
def top_attack_labels(f: Filters, limit: int = 8) -> pd.DataFrame:
    return _scoped(
        "WITH labels AS (SELECT label, attack_category, SUM(flows)::bigint AS flows "
        "FROM agg_hourly WHERE {where} AND attack_category <> 'Benign' "
        "GROUP BY label, attack_category) "
        "SELECT label, attack_category, flows, "
        "flows::float8 / NULLIF(SUM(flows) OVER (), 0) AS share "
        "FROM labels ORDER BY flows DESC, label LIMIT :limit",
        f,
        limit=limit,
    )


@st.cache_data(ttl=300)
def attack_mix(f: Filters) -> pd.DataFrame:
    return _scoped(
        "SELECT attack_category, SUM(flows)::bigint AS flows, "
        "SUM(flows)::float8 / NULLIF(SUM(SUM(flows)) OVER (), 0) AS share "
        "FROM agg_hourly WHERE {where} AND attack_category <> 'Benign' "
        "GROUP BY attack_category ORDER BY flows DESC, attack_category",
        f,
    )


@st.cache_data(ttl=300)
def flows_per_hour(f: Filters) -> pd.DataFrame:
    """Flows by hour of day, summed over the selected days."""
    return _scoped(
        "SELECT EXTRACT(HOUR FROM hour)::int AS hour, SUM(flows)::bigint AS flows "
        "FROM agg_hourly WHERE {where} AND hour IS NOT NULL GROUP BY 1 ORDER BY 1",
        f,
    )


@st.cache_data(ttl=300)
def top_ports(f: Filters, limit: int = 10, attack_only: bool = True) -> pd.DataFrame:
    """The busiest destination ports; the capped "other" bucket (port -1) never ranks."""
    return _scoped(
        "SELECT dst_port, SUM(flows)::bigint AS flows FROM agg_ports "
        "WHERE {where} AND dst_port <> -1 "
        "AND (NOT :attack_only OR attack_category <> 'Benign') "
        "GROUP BY dst_port ORDER BY flows DESC, dst_port LIMIT :limit",
        f,
        time="day",
        limit=limit,
        attack_only=attack_only,
    )


# Timeline (UI-03)


@st.cache_data(ttl=300)
def capture_days(f: Filters) -> pd.DataFrame:
    """Each capture day with its flows and attack flows (0 without a label)."""
    return _scoped(
        "SELECT hour::date AS day, SUM(flows)::bigint AS flows, "
        "COALESCE(SUM(flows) FILTER (WHERE attack_category <> 'Benign'), 0)::bigint "
        "AS attack_flows FROM agg_hourly WHERE {where} AND hour IS NOT NULL "
        "GROUP BY 1 ORDER BY 1",
        f,
    )


@st.cache_data(ttl=300)
def attack_flows_per_day(f: Filters) -> pd.DataFrame:
    return _scoped(
        "SELECT hour::date AS day, attack_category, SUM(flows)::bigint AS flows "
        "FROM agg_hourly WHERE {where} AND hour IS NOT NULL "
        "AND attack_category <> 'Benign' GROUP BY 1, 2 ORDER BY 1, 2",
        f,
    )


@st.cache_data(ttl=300)
def flows_per_hour_on(f: Filters, day: date) -> pd.DataFrame:
    """Flows per hour and label on one capture day, Benign included."""
    return _scoped(
        "SELECT EXTRACT(HOUR FROM hour)::int AS hour, label, attack_category, "
        "SUM(flows)::bigint AS flows FROM agg_hourly "
        "WHERE {where} AND hour >= :day AND hour < :day + INTERVAL '1 day' "
        "GROUP BY 1, 2, 3 ORDER BY 1, flows DESC, label",
        f,
        day=day,
    )


@st.cache_data(ttl=300)
def busiest_hours(f: Filters, limit: int = 5) -> pd.DataFrame:
    """The hours with the most flows; the main category is the largest in that hour."""
    return _scoped(
        "WITH per_hour AS (SELECT hour, attack_category, SUM(flows) AS flows "
        "FROM agg_hourly WHERE {where} AND hour IS NOT NULL GROUP BY 1, 2), "
        "ranked AS (SELECT hour, SUM(flows) OVER (PARTITION BY hour) AS total, "
        "attack_category, ROW_NUMBER() OVER "
        "(PARTITION BY hour ORDER BY flows DESC, attack_category) AS place FROM per_hour) "
        "SELECT hour::date AS day, EXTRACT(HOUR FROM hour)::int AS hour, "
        "total::bigint AS flows, attack_category AS main_category FROM ranked "
        "WHERE place = 1 ORDER BY flows DESC, day, hour LIMIT :limit",
        f,
        limit=limit,
    )


# Targets (UI-04)

PROTOCOL_ORDER = ["TCP", "UDP", "ICMP", "Other"]


@st.cache_data(ttl=300)
def protocol_mix(f: Filters) -> pd.DataFrame:
    """Each category's flows per protocol, with the share within the category."""
    frame = _scoped(
        "SELECT attack_category, protocol, SUM(flows)::bigint AS flows FROM agg_ports "
        "WHERE {where} GROUP BY 1, 2",
        f,
        time="day",
    )
    frame["protocol"] = frame["protocol"].map(protocol_name)
    frame = frame.groupby(["attack_category", "protocol"], dropna=False, as_index=False)[
        "flows"
    ].sum()
    totals = frame.groupby("attack_category", dropna=False)["flows"].transform("sum")
    frame["share"] = frame["flows"] / totals
    frame["_category"] = frame["attack_category"].map(
        lambda c: ATTACK_CATEGORIES.index(c) if c in ATTACK_CATEGORIES else len(ATTACK_CATEGORIES)
    )
    frame["_protocol"] = frame["protocol"].map(PROTOCOL_ORDER.index)
    frame = frame.sort_values(["_category", "_protocol"]).drop(columns=["_category", "_protocol"])
    return frame.reset_index(drop=True)


@st.cache_data(ttl=300)
def main_ports(f: Filters) -> pd.DataFrame:
    """Each attack category's busiest port and the next one, with their shares of its flows.

    The capped "other" bucket (port -1) counts in the shares but never ranks.
    """
    return _scoped(
        "WITH per_port AS (SELECT attack_category, dst_port, SUM(flows) AS flows FROM agg_ports "
        "WHERE {where} AND attack_category <> 'Benign' GROUP BY 1, 2), "
        "shares AS (SELECT attack_category, dst_port, "
        "flows::float8 / SUM(flows) OVER (PARTITION BY attack_category) AS share, "
        "ROW_NUMBER() OVER (PARTITION BY attack_category "
        "ORDER BY dst_port = -1, flows DESC, dst_port) AS place FROM per_port) "
        "SELECT m.attack_category, m.dst_port AS main_port, m.share AS main_share, "
        "n.dst_port AS next_port, n.share AS next_share FROM shares m "
        "LEFT JOIN shares n ON n.attack_category = m.attack_category AND n.place = 2 "
        "AND n.dst_port <> -1 "
        "WHERE m.place = 1 AND m.dst_port <> -1 "
        "ORDER BY array_position(CAST(:order AS text[]), m.attack_category)",
        f,
        time="day",
        order=list(ATTACK_CATEGORIES),
    )


# Pipeline (UI-07): the whole environment, so no filters


@st.cache_data(ttl=300)
def datasets_table() -> pd.DataFrame:
    """Every dataset with its file count and last run, the baseline first."""
    return _read(
        "SELECT d.dataset_id, d.display_name, COUNT(DISTINCT r.file_key) AS files, "
        "d.contract_name, d.contract_version, d.row_count, MAX(r.started_at) AS last_run_at, "
        "d.status FROM datasets d LEFT JOIN ingestion_runs r USING (dataset_id) "
        "GROUP BY d.dataset_id ORDER BY d.dataset_id = :baseline DESC, d.display_name",
        baseline=BASELINE,
    )


@st.cache_data(ttl=300)
def recent_runs(limit: int = 20) -> pd.DataFrame:
    return _read(
        "SELECT run_id, file_key, started_at, ended_at, rows_loaded, rows_rejected, status "
        "FROM ingestion_runs ORDER BY run_id DESC LIMIT :limit",
        limit=limit,
    )


@st.cache_data(ttl=300)
def quarantined_files() -> pd.DataFrame:
    """Files whose latest run was quarantined, newest first."""
    return _read(
        "WITH latest AS (SELECT DISTINCT ON (file_key) run_id, dataset_id, file_key, status, "
        "message, report_key, draft_contract_key FROM ingestion_runs "
        "ORDER BY file_key, run_id DESC) "
        "SELECT run_id, dataset_id, file_key, message, report_key, draft_contract_key "
        "FROM latest WHERE status = 'quarantined' ORDER BY run_id DESC"
    )


# Data quality (UI-06): the latest loaded run of each file in one dataset


@st.cache_data(ttl=300)
def cleaning_steps(dataset_id: str) -> pd.DataFrame:
    return _read(
        "WITH latest AS (SELECT DISTINCT ON (file_key) run_id FROM ingestion_runs "
        "WHERE dataset_id = :dataset_id AND status = 'loaded' ORDER BY file_key, run_id DESC) "
        "SELECT step, SUM(rows_affected)::bigint AS rows_affected "
        "FROM quality_steps WHERE run_id IN (SELECT run_id FROM latest) GROUP BY step "
        "ORDER BY array_position(CAST(:steps AS text[]), step)",
        dataset_id=dataset_id,
        steps=list(QUALITY_STEPS),
    )


@st.cache_data(ttl=300)
def column_issues(dataset_id: str) -> pd.DataFrame:
    """Columns with nulls, infinities or one value, summed over the dataset's files.

    A column counts as constant only when every file reports it so.
    """
    return _read(
        "WITH latest AS (SELECT DISTINCT ON (file_key) run_id FROM ingestion_runs "
        "WHERE dataset_id = :dataset_id AND status = 'loaded' ORDER BY file_key, run_id DESC) "
        "SELECT column_name, nulls, infinite, action FROM ("
        "SELECT column_name, SUM(nulls)::bigint AS nulls, SUM(infinite)::bigint AS infinite, "
        "CASE WHEN BOOL_AND(action = 'constant, hidden') "
        "AND COUNT(*) = (SELECT COUNT(*) FROM latest) THEN 'constant, hidden' "
        "WHEN SUM(infinite) > 0 THEN 'infinite set to null' "
        "WHEN SUM(nulls) > 0 THEN 'kept as null' END AS action "
        "FROM quality_columns WHERE run_id IN (SELECT run_id FROM latest) "
        "GROUP BY column_name) issues "
        "WHERE action IS NOT NULL ORDER BY nulls + infinite DESC, column_name",
        dataset_id=dataset_id,
    )


# Feature explorer (UI-05): distributions from the stratified sample in flow_sample

# A non-number extra reads as null, and CASE keeps the cast from ever seeing text
_EXTRA_VALUE = (
    "CASE WHEN jsonb_typeof(extras -> :field) = 'number' THEN (extras ->> :field)::float8 END"
)


def _field_value(f: Filters, field: str) -> tuple[str, dict[str, object]]:
    """The SQL for one field's value: a whitelisted canonical column, or a bound extras key."""
    if field in NUMERIC_FIELDS and field in f.fields:
        return field, {}
    if field in f.extra_fields:
        return _EXTRA_VALUE, {"field": field}
    raise ValueError(f"unknown field {field!r}")


# Enough sampled rows to tell a numeric extra from a text one without reading every row
EXTRAS_PROBE_ROWS = 500
STAT_COLUMNS = ["samples", "p5", "q1", "median", "q3", "p95", "mean"]


@st.cache_data(ttl=300)
def _numeric_extras(dataset_id: str, extra_fields: tuple[str, ...]) -> pd.DataFrame:
    sampled = _read(
        "WITH probe AS (SELECT extras FROM flow_sample WHERE dataset_id = :dataset_id "
        "LIMIT :rows) SELECT key AS field FROM probe, jsonb_each(extras) GROUP BY key "
        "HAVING BOOL_AND(jsonb_typeof(value) IN ('number', 'null')) "
        "AND BOOL_OR(jsonb_typeof(value) = 'number') ORDER BY key",
        dataset_id=dataset_id,
        rows=EXTRAS_PROBE_ROWS,
    )
    issues = column_issues(dataset_id)
    constant = set(issues.loc[issues["action"] == "constant, hidden", "column_name"])
    keep = sampled["field"].isin(extra_fields) & ~sampled["field"].isin(constant)
    return sampled[keep].reset_index(drop=True)


def numeric_extras(f: Filters) -> pd.DataFrame:
    """Extra fields whose sampled values are numbers, less the columns found constant.

    It depends only on the dataset, so changing the other filters does not run it again.
    """
    return _numeric_extras(f.dataset_id, tuple(f.extra_fields))


def _percentiles(prefix: str, only: str) -> str:
    """The statistics columns, all over one field's values or FILTERed to some of them."""
    where = f" FILTER (WHERE {only})" if only else ""
    within = [
        f"percentile_cont({q}) WITHIN GROUP (ORDER BY v){where} AS {prefix}{name}"
        for q, name in ((0.05, "p5"), (0.25, "q1"), (0.5, "median"), (0.75, "q3"), (0.95, "p95"))
    ]
    return ", ".join(
        [f"COUNT(*){where} AS {prefix}samples", *within, f"AVG(v){where} AS {prefix}mean"]
    )


@st.cache_data(ttl=300)
def _field_stats(f: Filters, field: str) -> pd.DataFrame:
    value, params = _field_value(f, field)
    # Every value, and values above 0 for a log scale, in one pass over the sample
    return _scoped(
        "SELECT attack_category, {every}, {positive} "
        "FROM (SELECT attack_category, {value} AS v FROM flow_sample WHERE {where}) sampled "
        "WHERE v IS NOT NULL GROUP BY attack_category "
        "ORDER BY array_position(CAST(:order AS text[]), attack_category)",
        f,
        time="ts",
        fragments={
            "value": value,
            "every": _percentiles("", ""),
            "positive": _percentiles("positive_", "v > 0"),
        },
        order=list(ATTACK_CATEGORIES),
        **params,
    )


def field_stats(f: Filters, field: str, positive_only: bool) -> pd.DataFrame:
    """Percentiles and mean of one field per category; positive_only for a log scale.

    Both versions come from one cached query, since the page shows both on every rerun.
    """
    stats = _field_stats(f, field)
    if not positive_only:
        return stats[["attack_category", *STAT_COLUMNS]].reset_index(drop=True)
    positive = stats[stats["positive_samples"] > 0]
    renamed = positive[["attack_category", *(f"positive_{c}" for c in STAT_COLUMNS)]]
    return renamed.set_axis(["attack_category", *STAT_COLUMNS], axis=1).reset_index(drop=True)


@st.cache_data(ttl=300)
def field_histogram(f: Filters, field: str, log: bool, bins: int = 30) -> pd.DataFrame:
    """Sample counts per category in equal bins; on a log scale the bins are equal in log10
    and values of 0 or less are left out."""
    value, params = _field_value(f, field)
    frame = _scoped(
        "WITH kept AS (SELECT attack_category, {scale} AS t FROM "
        "(SELECT attack_category, {value} AS v FROM flow_sample WHERE {where}) sampled "
        "WHERE v IS NOT NULL AND (NOT :log OR v > 0)), "
        "bounds AS (SELECT MIN(t) AS lo, MAX(t) AS hi FROM kept) "
        "SELECT attack_category, LEAST(width_bucket(t, lo, CASE WHEN hi > lo THEN hi "
        "ELSE lo + 1 END, :bins), :bins) AS bucket, COUNT(*) AS samples, "
        "MIN(lo) AS lo, MIN(CASE WHEN hi > lo THEN hi ELSE lo + 1 END) AS hi "
        "FROM kept, bounds GROUP BY attack_category, bucket "
        "ORDER BY array_position(CAST(:order AS text[]), attack_category), bucket",
        f,
        time="ts",
        fragments={"value": value, "scale": "log(v)" if log else "v"},
        log=log,
        bins=bins,
        order=list(ATTACK_CATEGORIES),
        **params,
    )
    width = (frame["hi"] - frame["lo"]) / bins
    start = frame["lo"] + (frame["bucket"] - 1) * width
    edges = pd.DataFrame({"bin_start": start, "bin_end": start + width})
    if log:
        edges = 10**edges
    return pd.concat([frame[["attack_category"]], edges, frame[["samples"]]], axis=1)

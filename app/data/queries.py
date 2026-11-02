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
from app.data.fields import ATTACK_CATEGORIES
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
    template: str, f: Filters, *, time: str = "hour", categories: bool = True, **params: object
) -> pd.DataFrame:
    """Run a query whose {where} placeholder takes the viewer's filters (see _scope).

    The clause is built only from constants in this module; every value is a bound parameter.
    """
    where, scope_params = _scope(f, time=time, categories=categories)
    return _read(template.format(where=where), **scope_params, **params)


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

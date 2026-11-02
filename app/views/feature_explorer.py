"""Feature explorer (UI-05): which flow features separate attacks from normal traffic,
including columns a new dataset brought with it.

Distributions come from the stratified sample; the Flows column counts every flow.
"""

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.filters import Filters, page_filters
from app.components.format import compact, with_unit
from app.components.layout import chart_card, load_or_warn, page_header
from app.data import queries
from app.data.fields import NUMERIC_FIELDS

BOX_NOTE = "box = 25th to 75th percentile, white line = median, whiskers = 5th to 95th percentile"
LEFT_OUT = "values of 0 or less left out"


def field_label(name: str) -> str:
    label, unit = NUMERIC_FIELDS.get(name, (name, ""))
    return f"{label} ({unit})" if name in NUMERIC_FIELDS else name


def summary(f: Filters, field: str) -> pd.DataFrame:
    """Every value's statistics per category, beside the flow count of each category."""
    stats = queries.field_stats(f, field, positive_only=False)
    if f.has_label:
        flows = queries.flows_by_category(f)
        return stats.merge(flows, on="attack_category", how="left")
    return stats.assign(flows=int(queries.kpi_totals(f).iloc[0]["flows"]))


def summary_table(df: pd.DataFrame, unit: str) -> None:
    table = pd.DataFrame(
        {
            "Category": df["attack_category"].astype(object).fillna(charts.ALL_TRAFFIC),
            "Flows": df["flows"].map(compact),
            "Median": df["median"].map(lambda v: with_unit(v, unit)),
            "95th percentile": df["p95"].map(lambda v: with_unit(v, unit)),
            "Mean": df["mean"].map(lambda v: with_unit(v, unit)),
        }
    )
    st.dataframe(table, hide_index=True)


page_header("Feature explorer")
f = page_filters()
st.caption(
    "Compare any numeric field across attack categories"
    if f.has_label
    else "Compare any numeric field across all traffic"
)
extras = load_or_warn("Fields", lambda: queries.numeric_extras(f))
fields = [name for name in NUMERIC_FIELDS if name in f.fields]
fields += [] if extras is None else extras["field"].tolist()
if not fields:
    st.info("This dataset has no numeric field to compare.")
    st.stop()

field_column, chart_column, scale_column = st.columns(3)
with field_column:
    field = st.selectbox("Field", fields, format_func=field_label, key="fx_field")
with chart_column:
    chart = st.selectbox("Chart", ["Box plot", "Histogram"], key="fx_chart")
with scale_column:
    log = st.toggle("Log scale", value=True, key="fx_log")
if f.extra_fields:
    st.info(f"Fields kept as extras: {', '.join(f.extra_fields)}.")

label, unit = NUMERIC_FIELDS.get(field, (field, ""))
title = f"{label} by category" if f.has_label else f"{label} across all traffic"
if chart == "Box plot":
    chart_card(
        title,
        f"Log scale · {BOX_NOTE} · {LEFT_OUT}" if log else BOX_NOTE,
        lambda: queries.field_stats(f, field, positive_only=log),
        lambda df: charts.show(charts.box_from_stats(df, log=log)),
        filters=f,
        needs=(field,),
    )
else:
    chart_card(
        title,
        f"Log scale · log-spaced bins · {LEFT_OUT}" if log else "Linear bins",
        lambda: queries.field_histogram(f, field, log),
        lambda df: charts.show(charts.histogram_from_bins(df, log=log)),
        filters=f,
        needs=(field,),
    )
chart_card(
    "Summary statistics",
    f"{label} per category" if f.has_label else f"{label} over all traffic",
    lambda: summary(f, field),
    lambda df: summary_table(df, unit),
    filters=f,
    needs=(field,),
)

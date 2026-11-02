"""Timeline (UI-03): when attacks happen, and whether they come in bursts."""

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.filters import page_filters
from app.components.format import compact, date_label, day_label, hour_label
from app.components.layout import NO_FLOWS, chart_card, load_or_warn, page_header
from app.data import queries

DAY_KEY = "timeline_day"
HOURS = list(range(24))


def day_chart(df: pd.DataFrame, selected) -> None:
    days = list(dict.fromkeys(df["day"]))
    fig = charts.stacked(
        df.assign(day=df["day"].map(day_label)), "day", "flows", "attack_category", totals=True
    )
    if selected in days:  # shade the chosen day's bar
        at = days.index(selected)
        fig.add_vrect(
            x0=at - 0.5,
            x1=at + 0.5,
            fillcolor=charts.PRIMARY,
            opacity=0.08,
            line_width=0,
            layer="below",
        )
    charts.show(fig)


def full_day(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Hourly flows for all 24 hours of the day, missing hours as zero."""
    table = df.pivot_table(index="hour", columns=by, values="flows", aggfunc="sum", fill_value=0)
    table = table.reindex(HOURS, fill_value=0)
    long = table.reset_index().melt(id_vars="hour", var_name=by, value_name="flows")
    return long.assign(hour=long["hour"].map(hour_label))


def hourly_chart(df: pd.DataFrame, labelled: bool) -> None:
    if labelled:
        charts.show(
            charts.stacked(full_day(df, "attack_category"), "hour", "flows", "attack_category")
        )
    else:
        totals = full_day(df.assign(traffic="All traffic"), "traffic")
        charts.show(charts.bars(totals, "flows", "hour", horizontal=False))


def peak_caption(df: pd.DataFrame, labelled: bool) -> str:
    per_hour = df.groupby("hour")["flows"].sum()
    hour = int(per_hour.idxmax())
    between = f"between {hour_label(hour)} and {hour_label((hour + 1) % 24)}"
    if not labelled:
        return f"Peak: {compact(per_hour.max())} flows {between}"
    top = df[df["hour"] == hour].sort_values(["flows", "label"], ascending=[False, True]).iloc[0]
    return f"{top['label']} sent {compact(top['flows'])} flows {between}"


def busiest_table(df: pd.DataFrame, labelled: bool) -> None:
    table = pd.DataFrame(
        {
            "Day": df["day"].map(day_label),
            "Hour": df["hour"].map(hour_label),
            "Flows": df["flows"].map(compact),
        }
    )
    if labelled:
        table["Main category"] = df["main_category"]
    st.dataframe(table, hide_index=True)


page_header("Timeline")
f = page_filters()
st.caption(
    "Benign traffic is hidden in the daily view so attacks stay visible"
    if f.has_label
    else "This dataset has no label, so the daily attack view is hidden"
)
days_frame = load_or_warn("Capture days", lambda: queries.capture_days(f))
if days_frame is None:
    st.stop()
if days_frame.empty:
    st.info(NO_FLOWS)
    st.stop()
days = days_frame["day"].tolist()
busiest_day = days_frame.loc[days_frame["attack_flows"].idxmax(), "day"]
default = busiest_day if f.has_label and days_frame["attack_flows"].max() > 0 else days[0]
if st.session_state.get(DAY_KEY) not in days:  # a day the filters no longer cover
    st.session_state.pop(DAY_KEY, None)
selected = st.session_state.get(DAY_KEY, default)

chart_card(
    "Attack flows per capture day",
    f"Each capture day carries one attack campaign · {day_label(selected)} selected",
    lambda: queries.attack_flows_per_day(f),
    lambda df: day_chart(df, selected),
    filters=f,
    needs=("label", "timestamp"),
)
picker = {} if DAY_KEY in st.session_state else {"index": days.index(default)}
selected = st.selectbox("Capture day", days, format_func=date_label, key=DAY_KEY, **picker)

left, right = st.columns(2)
with left:
    chart_card(
        f"Flows per hour on {date_label(selected)}",
        lambda df: peak_caption(df, f.has_label),
        lambda: queries.flows_per_hour_on(f, selected),
        lambda df: hourly_chart(df, f.has_label),
        filters=f,
        needs=("timestamp",),
    )
with right:
    chart_card(
        "Busiest hours",
        "All capture days, attack and benign flows",
        lambda: queries.busiest_hours(f),
        lambda df: busiest_table(df, f.has_label),
        filters=f,
        needs=("timestamp",),
    )

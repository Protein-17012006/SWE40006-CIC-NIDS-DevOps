"""Overview (UI-02, UI-08, UI-09): how much traffic is malicious, and which attacks are common.

A dataset without a label gets the layout of Figma frame 07: traffic charts first, then the
label-based charts as hidden cards.
"""

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.filters import Filters, page_filters
from app.components.format import compact, hour_label, percent, plural, span_label, stamp_label
from app.components.layout import chart_card, kpi_tile, load_or_warn, page_header
from app.data import queries
from app.data.ports import port_label


def new_columns(f: Filters) -> list[str]:
    """New columns the dataset's latest runs reported, in the order they first appeared."""
    files = load_or_warn("New columns", lambda: queries.dataset_files(f.dataset_id))
    names: list[str] = []
    for columns in [] if files is None else files["new_columns"]:
        names += [c for c in columns or () if c not in names]
    return names


def show_tiles(tiles: list[tuple[str, str, str]]) -> None:
    for column, (label, value, caption) in zip(st.columns(4), tiles, strict=True):
        with column:
            kpi_tile(label, value, caption)


def labels_table(df: pd.DataFrame) -> None:
    table = pd.DataFrame(
        {
            "Label": df["label"],
            "Category": df["attack_category"],
            "Flows": df["flows"].map(compact),
            "Share": df["share"].map(percent),
        }
    )
    st.dataframe(table, hide_index=True)


def hourly_bars(df: pd.DataFrame) -> None:
    hours = df.assign(hour=df["hour"].map(hour_label))
    charts.show(charts.bars(hours, "flows", "hour", horizontal=False))


def port_bars(df: pd.DataFrame) -> None:
    charts.show(charts.bars(df.assign(port=df["dst_port"].map(port_label)), "flows", "port"))


def category_card(f: Filters, span: str) -> None:
    chart_card(
        "Flows by category",
        f"Log scale · {span}",
        lambda: queries.flows_by_category(f),
        lambda df: charts.show(
            charts.bars(df, "flows", "attack_category", color="attack_category", log=True)
        ),
        filters=f,
        needs=("label",),
    )


def mix_card(f: Filters) -> None:
    chart_card(
        "Attack mix",
        "Share of attack flows by category",
        lambda: queries.attack_mix(f),
        lambda df: charts.show(charts.share_bar(df, "attack_category", "share")),
        filters=f,
        needs=("label",),
    )


page_header("Overview")
f = page_filters()
totals = load_or_warn("KPI tiles", lambda: queries.kpi_totals(f))
if totals is None:
    st.stop()
t = totals.iloc[0]
flows, attack_flows, days = int(t["flows"]), int(t["attack_flows"]), int(t["capture_days"])
span = span_label(t["first_day"], t["last_day"]) if days else "no capture time"
context = [f.display_name, f"{compact(flows)} flows", f"{plural(days, 'capture day')}, {span}"]
if f.loaded_at is not None:
    context.append(f"last loaded {stamp_label(f.loaded_at)}")
st.caption(" · ".join(context))
flows_tile = ("Flows", compact(flows), plural(days, "capture day"))

if f.has_label:
    categories = plural(int(t["categories"]), "category", "categories")
    show_tiles(
        [
            flows_tile,
            (
                "Attack share",
                percent(attack_flows / flows) if flows else "—",
                f"{compact(attack_flows)} attack flows",
            ),
            ("Attack types", str(int(t["attack_types"])), f"in {categories}"),
            ("Capture days", str(days), span),
        ]
    )
    left, right = st.columns(2)
    with left:
        category_card(f, span)
    with right:
        chart_card(
            "Top attack labels",
            f"Share of {compact(attack_flows)} attack flows",
            lambda: queries.top_attack_labels(f),
            labels_table,
            filters=f,
            needs=("label",),
        )
    mix_card(f)
else:
    added = new_columns(f)
    fourth = (
        ("New columns", str(len(added)), ", ".join(added))
        if added
        else ("Capture days", str(days), span)
    )
    show_tiles(
        [
            flows_tile,
            ("Attack share", "—", "no label column"),
            ("Attack types", "—", "no label column"),
            fourth,
        ]
    )
    note = "This file has no label column, so the attack-category charts are hidden. "
    if added:
        verb = "appears" if len(added) == 1 else "appear"
        note += (
            f"Traffic charts still work, and the {plural(len(added), 'new column')} "
            f"{verb} in the Feature explorer."
        )
    else:
        note += "Traffic charts still work."
    st.info(note)
    left, right = st.columns(2)
    with left:
        chart_card(
            "Flows per hour",
            f"All traffic · {span}",
            lambda: queries.flows_per_hour(f),
            hourly_bars,
            filters=f,
            needs=("timestamp",),
        )
    with right:
        chart_card(
            "Top destination ports",
            "All traffic · linear scale",
            lambda: queries.top_ports(f, 8, attack_only=False),
            port_bars,
            filters=f,
            needs=("dst_port",),
        )
    left, right = st.columns(2)
    with left:
        category_card(f, span)
    with right:
        mix_card(f)

"""Targets (UI-04): which ports and protocols each attack aims at."""

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.filters import page_filters
from app.components.format import percent, plural
from app.components.layout import chart_card, page_header
from app.data import queries
from app.data.ports import port_label


def protocol_chart(df: pd.DataFrame) -> None:
    # Without a label every category is null, so the column holds floats until cast
    named = df.assign(category=df["attack_category"].astype(object).fillna(charts.ALL_TRAFFIC))
    fig = charts.stacked(
        named,
        "category",
        "flows",
        "protocol",
        percent=True,
        horizontal=True,
        order=queries.PROTOCOL_ORDER,
        colors=charts.PROTOCOL_COLORS,
    )
    charts.show(fig)


def next_port(port: float, share: float) -> str:
    return "—" if pd.isna(port) else f"{port_label(int(port))} ({percent(share)})"


def main_ports_table(df: pd.DataFrame) -> None:
    table = pd.DataFrame(
        {
            "Category": df["attack_category"],
            "Main port": df["main_port"].map(lambda p: port_label(int(p))),
            "Share of its flows": df["main_share"].map(percent),
            "Next port": [
                next_port(p, s) for p, s in zip(df["next_port"], df["next_share"], strict=True)
            ],
        }
    )
    st.dataframe(table, hide_index=True)


page_header("Targets")
f = page_filters()
if f.has_label:
    selected = plural(len(f.categories), "attack category", "attack categories")
    st.caption(f"Destination ports and protocols of attack traffic · {selected} selected")
else:
    st.caption("Destination ports and protocols of all traffic · this dataset has no label")
st.info('Ports outside the top 50 per day, category and protocol are counted together as "other".')

left, right = st.columns(2)
with left:
    chart_card(
        "Top 10 destination ports",
        "Attack flows · linear scale" if f.has_label else "All traffic · linear scale",
        lambda: queries.top_ports(f, 10, attack_only=f.has_label),
        lambda df: charts.show(charts.port_bars(df)),
        filters=f,
        needs=("dst_port",),
    )
with right:
    chart_card(
        "Protocol mix by category",
        "Share of flows per protocol, in TCP / UDP / ICMP order",
        lambda: queries.protocol_mix(f),
        protocol_chart,
        filters=f,
        needs=("protocol",),
    )
chart_card(
    "Main port per attack category",
    "Where each category sends most of its flows",
    lambda: queries.main_ports(f),
    main_ports_table,
    filters=f,
    needs=("label", "dst_port"),
)

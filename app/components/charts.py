"""Plotly figures for the cards: the category colours, value labels and one height everywhere.

Streamlit's Plotly theme applies the Material fonts; these helpers only choose colours, axes
and labels, so every page draws the same way.
"""

from collections.abc import Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.components.format import compact, percent
from app.data.fields import ATTACK_CATEGORIES, CATEGORY_COLORS

PRIMARY = "#6750A4"
CHART_HEIGHT = 300
SHARE_BAR_HEIGHT = 120  # one bar; at 300 px it would be a block
PROTOCOL_COLORS = {"TCP": "#6750A4", "UDP": "#7D5260", "ICMP": "#625B71", "Other": "#CAC4D0"}
ALL_TRAFFIC = "All traffic"


def _finish(fig: go.Figure, *, legend: bool = False, height: int = CHART_HEIGHT) -> go.Figure:
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 24, "t": 8, "b": 0},
        showlegend=legend,
        # Stacked bars list their legend bottom-up by default; read it in series order instead
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.12,
            "x": 0,
            "title": None,
            "traceorder": "normal",
        },
        bargap=0.25,
    )
    return fig


# A log axis labels only the powers of ten; the 2s and 5s in between crowd it
LOG_AXIS = {"type": "log", "dtick": 1}


def _name(value: object) -> str:
    return ALL_TRAFFIC if value is None or pd.isna(value) else str(value)


def bars(
    df: pd.DataFrame,
    value: str,
    label: str,
    *,
    color: str | None = None,
    log: bool = False,
    horizontal: bool = True,
) -> go.Figure:
    """One bar per row with its value printed; category colours when color names that column."""
    values = df[value].tolist()
    labels = [str(v) for v in df[label]]
    marker = [CATEGORY_COLORS.get(c, PRIMARY) for c in df[color]] if color else PRIMARY
    common = {"marker_color": marker, "text": [compact(v) for v in values], "cliponaxis": False}
    if horizontal:
        trace = go.Bar(x=values, y=labels, orientation="h", textposition="outside", **common)
    else:
        trace = go.Bar(x=labels, y=values, textposition="outside", **common)
    fig = go.Figure(trace)
    value_axis = "xaxis" if horizontal else "yaxis"
    if log:
        fig.update_layout({value_axis: LOG_AXIS})
    if horizontal:
        fig.update_yaxes(autorange="reversed")  # the first row on top
    return _finish(fig)


def stacked(
    df: pd.DataFrame,
    x: str,
    value: str,
    color: str,
    *,
    percent: bool = False,
    horizontal: bool = False,
    order: Sequence[str] | None = None,
    colors: Mapping[str, str] | None = None,
    totals: bool = False,
) -> go.Figure:
    """Bars per x, stacked by the color column; percent stacks each bar to 100."""
    palette = colors or CATEGORY_COLORS
    positions = list(dict.fromkeys(df[x].tolist()))
    present = list(dict.fromkeys(df[color].tolist()))
    if order is not None:
        series = [s for s in order if s in present]
    elif color == "attack_category":
        series = [c for c in ATTACK_CATEGORIES if c in present]
    else:
        series = present
    table = df.pivot_table(index=x, columns=color, values=value, aggfunc="sum", fill_value=0)
    table = table.reindex(positions).fillna(0)
    if percent:
        table = table.div(table.sum(axis=1), axis=0) * 100
    fig = go.Figure()
    for name in series:
        values = table[name].tolist()
        axes = (
            {"x": values, "y": positions, "orientation": "h"}
            if horizontal
            else {"x": positions, "y": values}
        )
        fig.add_trace(go.Bar(name=str(name), marker_color=palette.get(name, PRIMARY), **axes))
    fig.update_layout(barmode="stack")
    if horizontal:
        fig.update_yaxes(autorange="reversed")
    if percent:
        fig.update_layout({"xaxis" if horizontal else "yaxis": {"ticksuffix": " %"}})
    if totals and not percent:
        for position, total in table.sum(axis=1).items():
            fig.add_annotation(x=position, y=total, text=compact(total), showarrow=False, yshift=10)
    return _finish(fig, legend=True)


def share_bar(df: pd.DataFrame, category: str, share: str) -> go.Figure:
    """One 100 % bar of shares, labelled on segments of 10 % or more, with the legend below."""
    fig = go.Figure()
    for name, value in zip(df[category], df[share], strict=True):
        fig.add_trace(
            go.Bar(
                name=str(name),
                x=[value * 100],
                y=[""],
                orientation="h",
                marker_color=CATEGORY_COLORS.get(name, PRIMARY),
                text=[percent(value) if value >= 0.10 else ""],
                textposition="inside",
                insidetextanchor="middle",
            )
        )
    fig.update_layout(barmode="stack", xaxis={"visible": False, "range": [0, 100]})
    return _finish(fig, legend=True, height=SHARE_BAR_HEIGHT)


def box_from_stats(stats: pd.DataFrame, *, log: bool) -> go.Figure:
    """Boxes from precomputed percentiles: 25th to 75th, whiskers at the 5th and 95th.

    Plotly draws a box's median in its line colour, so a white tick on top marks the median.
    """
    fig = go.Figure()
    names = [_name(v) for v in stats["attack_category"]]
    for name, row in zip(names, stats.itertuples(index=False), strict=True):
        colour = CATEGORY_COLORS.get(name, PRIMARY)
        fig.add_trace(
            go.Box(
                name=name,
                x=[name],
                q1=[row.q1],
                median=[row.median],
                q3=[row.q3],
                lowerfence=[row.p5],
                upperfence=[row.p95],
                fillcolor=colour,
                line={"color": colour},
                boxpoints=False,
            )
        )
    fig.add_trace(
        go.Scatter(
            x=names,
            y=stats["median"].tolist(),
            mode="markers",
            marker={"symbol": "line-ew", "size": 28, "line": {"color": "white", "width": 3}},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(boxmode="overlay")
    if log:
        fig.update_layout(yaxis=LOG_AXIS)
    return _finish(fig)


def histogram_from_bins(bins: pd.DataFrame, *, log: bool) -> go.Figure:
    """One step line per category over its bin edges, so overlapping categories stay readable."""
    fig = go.Figure()
    for value, group in bins.groupby("attack_category", sort=False, dropna=False):
        name = _name(value)
        edges = [*group["bin_start"].tolist(), group["bin_end"].iloc[-1]]
        counts = [*group["samples"].tolist(), group["samples"].iloc[-1]]
        fig.add_trace(
            go.Scatter(
                name=name,
                x=edges,
                y=counts,
                mode="lines",
                line={"shape": "hv", "color": CATEGORY_COLORS.get(name, PRIMARY), "width": 2},
            )
        )
    if log:
        fig.update_layout(xaxis=LOG_AXIS)
    return _finish(fig, legend=True)


def show(fig: go.Figure, *, key: str | None = None, select: bool = False) -> object:
    """Draw a figure in the app's theme; with select, return the viewer's clicked points."""
    options = {"theme": "streamlit", "config": {"displayModeBar": False}, "key": key}
    if select:
        return st.plotly_chart(fig, on_select="rerun", selection_mode="points", **options)
    return st.plotly_chart(fig, **options)

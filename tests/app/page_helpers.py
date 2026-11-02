"""Readers for AppTest results that the page tests share."""

import json


def tiles(at) -> dict[str, str]:
    """KPI tiles as metric label to value."""
    return {m.label: m.value for m in at.metric}


def captions(at) -> list[str]:
    return [c.value for c in at.caption]


def markdown(at) -> set[str]:
    return {m.value for m in at.markdown}


def x_axis(chart) -> dict:
    """A Plotly chart's x-axis layout, as the page sent it."""
    return json.loads(chart.proto.spec)["layout"].get("xaxis", {})

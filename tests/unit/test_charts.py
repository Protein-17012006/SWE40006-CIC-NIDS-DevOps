import pandas as pd

from app.components.charts import (
    PROTOCOL_COLORS,
    bars,
    box_from_stats,
    histogram_from_bins,
    hour_axis,
    share_bar,
    stacked,
)


def test_bars_use_category_colours_value_labels_and_log_axis():
    df = pd.DataFrame({"attack_category": ["Benign", "DDoS"], "flows": [3600, 2000]})
    fig = bars(df, "flows", "attack_category", color="attack_category", log=True)
    assert list(fig.data[0].marker.color) == ["#8F8D86", "#EB6834"]
    assert list(fig.data[0].text) == ["3.6 k", "2 k"] and fig.layout.xaxis.type == "log"


def test_single_measure_bars_use_primary():
    fig = bars(pd.DataFrame({"port": ["80 · HTTP"], "flows": [10]}), "flows", "port")
    assert fig.data[0].marker.color == "#6750A4" and fig.layout.height == 300


def test_stacked_keeps_the_given_order_and_colours():
    df = pd.DataFrame(
        {
            "day": ["14 Feb", "14 Feb", "21 Feb"],
            "attack_category": ["Botnet", "Brute force", "DDoS"],
            "flows": [200, 700, 2000],
        }
    )
    fig = stacked(df, "day", "flows", "attack_category", order=["DDoS", "Brute force", "Botnet"])
    assert [t.name for t in fig.data] == ["DDoS", "Brute force", "Botnet"]
    assert [t.marker.color for t in fig.data] == ["#EB6834", "#1BAF7A", "#E87BA4"]
    assert fig.layout.barmode == "stack"


def test_stacked_percent_shares_add_up_within_each_bar():
    df = pd.DataFrame(
        {"category": ["DDoS", "DDoS"], "protocol": ["TCP", "UDP"], "flows": [1990, 10]}
    )
    fig = stacked(
        df, "category", "flows", "protocol", percent=True, horizontal=True, colors=PROTOCOL_COLORS
    )
    assert [t.x[0] for t in fig.data] == [99.5, 0.5]
    assert [t.marker.color for t in fig.data] == [PROTOCOL_COLORS["TCP"], PROTOCOL_COLORS["UDP"]]
    # Shares are printed on segments of 10 % or more, so colour is not the only cue
    assert [t.text[0] for t in fig.data] == ["99.5 %", ""]


def test_protocol_colours_differ_in_lightness():
    """TCP, UDP and ICMP sit side by side; they must stay apart without hue (colour blindness)."""

    def lightness(hex_colour: str) -> float:
        r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
        return (max(r, g, b) + min(r, g, b)) / 510

    shades = sorted(lightness(PROTOCOL_COLORS[p]) for p in ("TCP", "UDP", "ICMP"))
    assert min(b - a for a, b in zip(shades, shades[1:], strict=False)) >= 0.15


def test_share_bar_labels_segments_of_ten_percent_or_more():
    df = pd.DataFrame(
        {"attack_category": ["DDoS", "DoS", "Infiltration"], "share": [0.6, 0.35, 0.05]}
    )
    fig = share_bar(df, "attack_category", "share")
    assert [t.text[0] for t in fig.data] == ["60.0 %", "35.0 %", ""]


def test_box_from_stats_uses_precomputed_fences():
    stats = pd.DataFrame(
        {
            "attack_category": ["DDoS"],
            "p5": [1.0],
            "q1": [2.0],
            "median": [3.0],
            "q3": [4.0],
            "p95": [5.0],
        }
    )
    box = box_from_stats(stats, log=False).data[0]
    assert (box.lowerfence[0], box.q1[0], box.median[0], box.q3[0], box.upperfence[0]) == (
        1,
        2,
        3,
        4,
        5,
    )
    assert box.fillcolor == "#EB6834"


def test_box_without_a_label_is_all_traffic_in_primary():
    stats = pd.DataFrame(
        {
            "attack_category": [None],
            "p5": [1.0],
            "q1": [2.0],
            "median": [3.0],
            "q3": [4.0],
            "p95": [5.0],
        }
    )
    box = box_from_stats(stats, log=True)
    assert box.data[0].name == "All traffic" and box.data[0].fillcolor == "#6750A4"
    assert box.layout.yaxis.type == "log"


def test_histogram_from_bins_one_trace_per_category():
    bins = pd.DataFrame(
        {
            "attack_category": ["Benign", "Benign", "DDoS"],
            "bin_start": [1.0, 10.0, 1.0],
            "bin_end": [10.0, 100.0, 10.0],
            "samples": [3, 2, 5],
        }
    )
    fig = histogram_from_bins(bins, log=True)
    assert [t.name for t in fig.data] == ["Benign", "DDoS"]
    # A step outline over the bin edges that starts and ends at 0
    assert list(fig.data[0].x) == [1.0, 1.0, 10.0, 100.0, 100.0]
    assert list(fig.data[0].y) == [0, 3, 2, 2, 0]
    assert fig.data[0].line.color == "#8F8D86" and fig.layout.xaxis.type == "log"


def test_histogram_drops_to_zero_across_empty_bins():
    """The query returns only bins with samples; a gap must not be drawn at the last height."""
    bins = pd.DataFrame(
        {
            "attack_category": ["Benign", "Benign"],
            "bin_start": [1.0, 100.0],
            "bin_end": [10.0, 1000.0],
            "samples": [3, 2],
        }
    )
    trace = histogram_from_bins(bins, log=True).data[0]
    assert list(trace.x) == [1.0, 1.0, 10.0, 100.0, 100.0, 1000.0, 1000.0]
    assert list(trace.y) == [0, 3, 0, 0, 2, 2, 0]


def test_hour_axis_labels_every_third_hour_level():  # 24 upright labels ran under the legend
    df = pd.DataFrame({"hour": [f"{h:02d}:00" for h in range(24)], "flows": range(24)})
    fig = hour_axis(bars(df, "flows", "hour", horizontal=False))
    assert fig.layout.xaxis.tickvals == tuple(f"{h:02d}:00" for h in range(0, 24, 3))
    assert fig.layout.xaxis.tickangle == 0

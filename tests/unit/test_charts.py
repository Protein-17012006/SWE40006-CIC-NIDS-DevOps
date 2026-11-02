import pandas as pd

from app.components.charts import (
    PROTOCOL_COLORS,
    bars,
    box_from_stats,
    histogram_from_bins,
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
    assert [t.marker.color for t in fig.data] == ["#6750A4", "#7D5260"]


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
    # A step line over the bin edges: the last count repeats to close the last bin
    assert list(fig.data[0].x) == [1.0, 10.0, 100.0] and list(fig.data[0].y) == [3, 2, 2]
    assert fig.data[0].line.color == "#8F8D86" and fig.layout.xaxis.type == "log"

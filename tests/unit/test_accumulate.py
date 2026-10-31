import json
from collections import Counter
from datetime import date

import pandas as pd
from pandas.testing import assert_frame_equal

from pipeline.accumulate import Aggregates, ColumnIssue, Deduplicator, Quality
from pipeline.clean import STEPS, CleanChunk

CATEGORY = {"Benign": "Benign", "Bot": "Botnet", "DDOS attack-HOIC": "DDoS"}


def T(hhmm: str, day: str = "2018-02-14") -> pd.Timestamp:
    return pd.Timestamp(f"{day} {hhmm}")


def _flows(times, labels, ports=None, extras=None) -> pd.DataFrame:
    n = len(labels)
    frame = pd.DataFrame(
        {
            "timestamp": pd.Series(times, dtype="datetime64[ns]"),
            "dst_port": pd.array(ports or [80] * n, dtype="Int64"),
            "protocol": pd.array([6] * n, dtype="Int64"),
            "flow_duration_us": pd.array([float(i) for i in range(n)], dtype="Float64"),
            "fwd_packets": pd.array([1] * n, dtype="Int64"),
            "bwd_packets": pd.array([1] * n, dtype="Int64"),
            "fwd_bytes": pd.array([10.0] * n, dtype="Float64"),
            "bwd_bytes": pd.array([10.0] * n, dtype="Float64"),
            "label": pd.array(labels, dtype="string"),
            "attack_category": pd.array([CATEGORY[x] for x in labels], dtype="string"),
        }
    )
    for name, values in (extras or {}).items():
        frame[name] = values
    return frame


def flows(*pairs: tuple[str, str]) -> pd.DataFrame:
    return _flows([T(t) for t, _ in pairs], [label for _, label in pairs])


def flows_of(label: str, n: int, day: str = "2018-02-14") -> pd.DataFrame:
    return _flows([T("10:00", day)] * n, [label] * n)


def ports(*values: int) -> pd.DataFrame:
    return _flows([T("10:00")] * len(values), ["Benign"] * len(values), ports=list(values))


def test_dedup_within_and_across_chunks():
    d = Deduplicator()
    a, n1 = d.drop(pd.DataFrame({"a": [1, 2, 2], "b": ["x", "y", "y"]}))
    b, n2 = d.drop(pd.DataFrame({"a": [2, 3], "b": ["y", "z"]}))
    assert (a["a"].tolist(), n1, b["a"].tolist(), n2) == ([1, 2], 1, [3], 1)


def test_dedup_keeps_rows_that_differ_in_one_column():
    kept, dropped = Deduplicator().drop(pd.DataFrame({"a": [1, 1], "b": ["x", "y"]}))
    assert (len(kept), dropped) == (2, 0)


def test_hourly_counts_split_by_label():
    agg = Aggregates()
    agg.add(flows(("08:10", "Benign"), ("08:50", "Benign"), ("09:05", "Bot")))
    assert agg.hourly().to_dict("records") == [
        {"hour": T("08:00"), "label": "Benign", "attack_category": "Benign", "flows": 2},
        {"hour": T("09:00"), "label": "Bot", "attack_category": "Botnet", "flows": 1},
    ]
    assert (agg.rows, agg.first_ts, agg.last_ts) == (3, T("08:10"), T("09:05"))


def test_hourly_adds_up_across_chunks():
    agg = Aggregates()
    agg.add(flows(("08:10", "Benign")))
    agg.add(flows(("08:20", "Benign"), ("08:30", "Benign")))
    assert agg.hourly()["flows"].tolist() == [3]


def test_rows_without_timestamp_or_label_have_nulls():
    agg = Aggregates()
    agg.add(flows_of("Benign", 4).drop(columns=["timestamp", "label", "attack_category"]))
    hourly, by_port = agg.hourly(), agg.ports()
    assert hourly["hour"].isna().all() and hourly["label"].isna().all()
    assert hourly["flows"].tolist() == [4] and by_port["day"].isna().all()
    assert agg.first_ts is None and agg.last_ts is None
    assert len(agg.sample()) == 4 and agg.sample()["ts"].isna().all()


def test_ports_keep_top_n_and_sum_the_rest():
    agg = Aggregates(top_ports=2)
    agg.add(ports(80, 80, 80, 80, 80, 443, 443, 443, 22, 21))
    result = agg.ports()
    assert sorted(result[["dst_port", "flows"]].itertuples(index=False, name=None)) == [
        (-1, 2),
        (80, 5),
        (443, 3),
    ]
    assert set(result["day"]) == {date(2018, 2, 14)} and set(result["protocol"]) == {6}


def test_ports_without_overflow_have_no_other_row():
    agg = Aggregates(top_ports=2)
    agg.add(ports(80, 443))
    assert -1 not in agg.ports()["dst_port"].tolist()


def test_sample_caps_common_classes_and_keeps_rare_ones_across_chunks():
    agg = Aggregates(sample_per_group=10)
    for _ in range(5):
        agg.add(flows_of("Benign", 100))
    agg.add(flows_of("Bot", 3))
    assert agg.sample()["attack_category"].value_counts().to_dict() == {"Benign": 10, "Botnet": 3}


def test_sample_is_stratified_by_day():
    agg = Aggregates(sample_per_group=5)
    agg.add(flows_of("Benign", 20, day="2018-02-14"))
    agg.add(flows_of("Benign", 20, day="2018-02-15"))
    days = agg.sample()["ts"].dt.date.value_counts().to_dict()
    assert days == {date(2018, 2, 14): 5, date(2018, 2, 15): 5}


def test_sample_is_deterministic_for_a_seed():
    def sampled(seed: int) -> pd.DataFrame:
        agg = Aggregates(sample_per_group=7, seed=seed)
        agg.add(flows_of("Benign", 50))
        return agg.sample()

    assert_frame_equal(sampled(1), sampled(1))
    assert not sampled(1)["flow_duration_us"].equals(sampled(2)["flow_duration_us"])


def test_sample_columns_and_json_safe_extras():
    agg = Aggregates()
    frame = flows(("08:10", "Benign"), ("08:20", "Benign"))
    frame["pkt_entropy"] = pd.array([float("nan"), 3.5], dtype="Float64")
    frame["geo_country"] = pd.array(["VN", None], dtype="string")
    agg.add(frame)
    sample = agg.sample()
    assert list(sample.columns) == [
        "ts",
        "label",
        "attack_category",
        "dst_port",
        "protocol",
        "flow_duration_us",
        "fwd_packets",
        "bwd_packets",
        "fwd_bytes",
        "bwd_bytes",
        "flow_bytes_per_s",
        "flow_packets_per_s",
        "src_ip",
        "dst_ip",
        "extras",
    ]
    extras = sorted(sample["extras"], key=lambda e: e["geo_country"] or "")
    assert extras == [
        {"pkt_entropy": 3.5, "geo_country": None},
        {"pkt_entropy": None, "geo_country": "VN"},
    ]
    json.dumps(extras, allow_nan=False)


def _chunk(steps=None, nulls=None, infinite=None) -> CleanChunk:
    counts = Counter(dict.fromkeys(STEPS, 0))
    counts.update(steps or {})
    return CleanChunk(
        pd.DataFrame(), 0, 0, counts, Counter(), Counter(nulls or {}), Counter(infinite or {})
    )


def test_quality_steps_include_every_step():
    q = Quality()
    q.add(_chunk(steps={"repeated_headers_dropped": 1, "labels_trimmed": 2}), pd.DataFrame(), 3)
    q.add(_chunk(steps={"labels_trimmed": 1}), pd.DataFrame(), 0)
    assert q.steps() == {
        "duplicates_removed": 3,
        "infinite_set_to_null": 0,
        "missing_kept_as_null": 0,
        "repeated_headers_dropped": 1,
        "labels_trimmed": 3,
    }


def test_quality_columns_and_their_actions():
    q = Quality()
    kept = pd.DataFrame(
        {
            "bwd_psh_flags": pd.array([0.0, 0.0], dtype="Float64"),
            "flow_bytes_per_s": pd.array([1.0, 2.0], dtype="Float64"),
            "x": pd.array([1.0, None], dtype="Float64"),
            "label": pd.array(["Benign", "Benign"], dtype="string"),
        }
    )
    q.add(_chunk(infinite={"flow_bytes_per_s": 2}, nulls={"x": 1, "flow_bytes_per_s": 2}), kept, 0)
    assert sorted(q.columns(), key=lambda c: c.column_name) == [
        ColumnIssue("bwd_psh_flags", 0, 0, "constant, hidden"),
        ColumnIssue("flow_bytes_per_s", 2, 2, "infinite set to null"),
        ColumnIssue("x", 1, 0, "kept as null"),
    ]


def test_a_column_constant_in_each_chunk_but_not_overall_is_not_constant():
    q = Quality()
    q.add(_chunk(), pd.DataFrame({"a": pd.array([1.0, 1.0], dtype="Float64")}), 0)
    q.add(_chunk(), pd.DataFrame({"a": pd.array([2.0, 2.0], dtype="Float64")}), 0)
    assert q.columns() == []


def test_an_all_null_numeric_column_is_constant():
    q = Quality()
    q.add(_chunk(nulls={"a": 2}), pd.DataFrame({"a": pd.array([None, None], dtype="Float64")}), 0)
    assert q.columns() == [ColumnIssue("a", 2, 0, "constant, hidden")]

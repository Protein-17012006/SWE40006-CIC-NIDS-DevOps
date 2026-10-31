import csv
import random
from collections import Counter
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from pipeline.clean import STEPS, clean_chunk, infer_extra_kinds, read_chunks, read_header
from pipeline.contracts import (
    Contract,
    FieldSource,
    load_contracts,
    match_contract,
    normalise_header,
)

WED = Path(__file__).resolve().parents[1] / "contracts/cse-cic-ids2018/wednesday-14-02-2018.csv"
SOURCE_HEADER = read_header(WED)
with WED.open(newline="") as _f:
    _ROWS = [dict(zip(SOURCE_HEADER, r, strict=True)) for r in list(csv.reader(_f))[1:]]
HEADER_ROW = {c: c for c in SOURCE_HEADER}
BASELINE = next(c for c in load_contracts() if c.name == "cse-cic-ids2018")


def row(**overrides: str) -> dict[str, str]:
    """The first data row (Benign, 14/02/2018 08:31:01), values replaced by source name."""
    return {**_ROWS[0], **overrides}


def rows(n: int) -> list[dict[str, str]]:
    return [dict(r) for r in _ROWS[:n]]


def scaled(**scales: float) -> Contract:
    fields = dict(BASELINE.fields)
    for name, scale in scales.items():
        fields[name] = FieldSource(column=fields[name].column, scale=scale)
    return BASELINE.model_copy(update={"fields": fields})


def without_label() -> Contract:
    fields = {k: v for k, v in BASELINE.fields.items() if k != "label"}
    return BASELINE.model_copy(update={"fields": fields, "label_map": {}})


def clean(records, contract=BASELINE, shuffle_columns=False, extra_header=None):
    header = list(SOURCE_HEADER) + list(extra_header or {})
    records = [{**r, **(extra_header or {})} for r in records]
    if shuffle_columns:
        header = random.Random(3).sample(header, len(header))
    chunk = pd.DataFrame([[r[c] for c in header] for r in records], columns=header, dtype=str)
    chunk.columns = normalise_header(header)
    match = match_contract(header, [contract])
    return clean_chunk(chunk, match, infer_extra_kinds(chunk, match.extras))


def test_steps_are_the_five_cleaning_steps():
    assert set(STEPS) == {
        "duplicates_removed",
        "infinite_set_to_null",
        "missing_kept_as_null",
        "repeated_headers_dropped",
        "labels_trimmed",
    }


def test_read_chunks_gives_text_with_normalised_columns(tmp_path):
    chunks = list(read_chunks(WED, chunk_rows=150))
    assert [len(c) for c in chunks] == [150, 50]
    assert chunks[0].columns[:3].tolist() == ["dst_port", "protocol", "timestamp"]
    assert chunks[0]["dst_port"].iloc[0] == "0"
    bom = tmp_path / "bom.csv"
    bom.write_bytes(b"\xef\xbb\xbfDst Port,Label\n80,Benign\n")
    assert read_header(bom) == ["Dst Port", "Label"]


def test_repeated_header_rows_are_dropped():
    out = clean([*rows(3), HEADER_ROW])
    assert (len(out.frame), out.rows_in, out.steps["repeated_headers_dropped"]) == (3, 4, 1)
    assert out.rejected == 0


def test_infinite_values_become_null():
    out = clean(
        [
            row(**{"Flow Byts/s": "Infinity", "Flow Pkts/s": "inf"}),
            row(**{"Flow Byts/s": "-Infinity"}),
        ]
    )
    assert out.frame["flow_bytes_per_s"].isna().all() and out.steps["infinite_set_to_null"] == 2
    assert out.infinite == Counter({"flow_bytes_per_s": 2, "flow_packets_per_s": 1})
    assert out.rejected == 0


def test_missing_values_are_kept_as_null():
    out = clean([row(**{"Flow Byts/s": "NaN"}), row(**{"Fwd Pkt Len Max": ""}), row()])
    assert out.steps["missing_kept_as_null"] == 2 and out.rejected == 0
    assert out.nulls == Counter({"flow_bytes_per_s": 1, "fwd_pkt_len_max": 1})
    assert out.frame["fwd_pkt_len_max"].isna().sum() == 1


def test_labels_are_trimmed_and_mapped():
    out = clean([row(Label=" Benign "), row(Label="DDOS attack-HOIC")])
    assert list(out.frame["label"]) == ["Benign", "DDOS attack-HOIC"]
    assert list(out.frame["attack_category"]) == ["Benign", "DDoS"]
    assert out.steps["labels_trimmed"] == 1


def test_unknown_labels_rejected_and_counted():
    out = clean([row(Label="Worm"), row(Label="Worm"), row()])
    assert (out.rejected, out.unknown_labels, len(out.frame)) == (2, Counter({"Worm": 2}), 1)


def test_invalid_rows_rejected():
    out = clean(
        [
            row(**{"Dst Port": "70000"}),
            row(Protocol="x"),
            row(**{"Flow Duration": "-5"}),
            row(Timestamp="yesterday"),
            row(**{"Dst Port": "80.5"}),
            row(Label=""),
            row(),
        ]
    )
    assert (out.rejected, len(out.frame), out.unknown_labels) == (6, 1, Counter())


def test_types_of_canonical_fields():
    frame = clean(rows(3)).frame
    assert frame["dst_port"].dtype == "Int64" and frame["fwd_packets"].dtype == "Int64"
    assert frame["flow_duration_us"].dtype == "Float64" and frame["label"].dtype == "string"
    assert frame["timestamp"].dtype == "datetime64[ns]"


def test_unit_scale_and_timestamp_format():
    out = clean([row(**{"Flow Duration": "2.5"})], contract=scaled(flow_duration_us=1000))
    assert out.frame["flow_duration_us"].iloc[0] == 2500.0
    assert out.frame["timestamp"].iloc[0] == pd.Timestamp("2018-02-14 08:31:01")


def test_extras_keep_normalised_names_and_kinds():
    out = clean([row(), row()], extra_header={"Geo Country": "VN"})
    assert out.frame["fwd_pkt_len_max"].dtype == "Float64"
    assert out.frame["geo_country"].dtype == "string"
    assert "Fwd Pkt Len Max" not in out.frame.columns


def test_extra_kinds_ignore_repeated_headers_and_special_values():
    chunk = pd.DataFrame(
        {"a": ["1", "inf", "NaN", "", "a"], "b": ["x", "1", "", "", "b"]}, dtype=str
    )
    assert infer_extra_kinds(chunk, ["a", "b"]) == {"a": "numeric", "b": "text"}


def test_extra_named_like_a_canonical_field_does_not_clash():
    out = clean(rows(2), contract=without_label())
    assert "attack_category" not in out.frame and "label" not in out.frame
    assert list(out.frame["label_extra"]) == ["Benign", "Benign"]


def test_columns_in_any_order_give_the_same_frame():
    assert_frame_equal(
        clean(rows(5)).frame, clean(rows(5), shuffle_columns=True).frame, check_like=True
    )

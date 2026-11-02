from dataclasses import replace
from datetime import date

from app.components.filters import Filters
from app.components.guard import missing

LABELLED = Filters(
    dataset_id="cse-cic-ids2018",
    display_name="cse-cic-ids2018",
    has_label=True,
    fields=("timestamp", "dst_port", "protocol", "flow_duration_us", "label", "attack_category"),
    extra_fields=("bwd_psh_flags", "fwd_pkt_len_max"),
    date_from=date(2018, 2, 14),
    date_to=date(2018, 2, 21),
    categories=("DoS", "DDoS"),
    row_count=7155,
    loaded_at=None,
)


def make(**overrides) -> Filters:
    return replace(LABELLED, **overrides)


def test_guard_label_timestamp_and_extras():
    unlabelled = make(
        has_label=False, fields=("timestamp", "dst_port"), extra_fields=("pkt_entropy",)
    )
    assert missing(unlabelled, ["label", "dst_port", "pkt_entropy"]) == ["label"]
    assert missing(make(fields=("dst_port",), date_from=None), ["timestamp"]) == ["timestamp"]


def test_guard_passes_a_complete_dataset():
    assert missing(LABELLED, ["label", "timestamp", "dst_port", "fwd_pkt_len_max"]) == []

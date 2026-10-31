import pytest
from pydantic import ValidationError

from app.data.fields import FIELD_NAMES
from pipeline.contracts import (
    Contract,
    ContractError,
    FieldSource,
    closest_contract,
    load_contracts,
    match_contract,
    missing_fields,
    normalise,
    normalise_header,
)

SOURCES = {
    "timestamp": "Timestamp",
    "dst_port": "Dst Port",
    "protocol": "Protocol",
    "flow_duration_us": "Flow Duration",
    "fwd_packets": "Tot Fwd Pkts",
    "bwd_packets": "Tot Bwd Pkts",
    "fwd_bytes": "TotLen Fwd Pkts",
    "bwd_bytes": "TotLen Bwd Pkts",
    "flow_bytes_per_s": "Flow Byts/s",
    "flow_packets_per_s": "Flow Pkts/s",
    "src_ip": "Src IP",
    "dst_ip": "Dst IP",
    "label": "Label",
}
HEADER = list(SOURCES.values())


def _contract(**overrides: object) -> dict:
    """A valid contract dict; canonical names override fields, None drops an entry."""
    data: dict = {
        "name": "test",
        "version": 1,
        "timestamp_format": "%d/%m/%Y %H:%M:%S",
        "fields": dict(SOURCES),
        "label_map": {"Benign": "Benign", "Bot": "Botnet"},
    }
    for key, value in overrides.items():
        target = data["fields"] if key in FIELD_NAMES or key == "foo" else data
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value
    return data


def _contract_obj(**overrides: object) -> Contract:
    return Contract.model_validate(_contract(**overrides))


def test_normalise():
    assert normalise(" Flow Byts/s ") == "flow_byts_s"
    assert normalise("﻿Dst Port") == "dst_port"
    assert normalise("Down/Up Ratio") == "down_up_ratio"
    assert normalise("Fwd Header Length.1") == "fwd_header_length_1"


def test_normalise_header_numbers_repeats():
    assert normalise_header(["Flow Byts/s", "Flow Byts s", "Label"]) == [
        "flow_byts_s",
        "flow_byts_s_2",
        "label",
    ]


def test_field_source_accepts_name_or_scale():
    c = _contract_obj(flow_duration_us={"column": "Flow Duration (ms)", "scale": 1000})
    assert c.fields["flow_duration_us"] == FieldSource(column="Flow Duration (ms)", scale=1000)
    assert c.fields["dst_port"] == FieldSource(column="Dst Port", scale=1.0)


def test_contract_rejects_missing_required_field():
    with pytest.raises(ValidationError, match="dst_port"):
        _contract_obj(dst_port=None)


@pytest.mark.parametrize(
    ("bad", "word"),
    [
        ({"foo": "Foo"}, "foo"),
        ({"label_map": {"Worm": "Worm"}}, "Worm"),
        ({"protocol": "TODO"}, "TODO"),
        ({"label_map": {"Benign": "TODO"}}, "TODO"),
    ],
)
def test_contract_rejects_unknown_field_category_and_todo(bad, word):
    with pytest.raises(ValidationError, match=word):
        _contract_obj(**bad)


def test_timestamp_needs_format_and_label_needs_map():
    with pytest.raises(ValidationError, match="timestamp_format"):
        _contract_obj(timestamp_format=None)
    with pytest.raises(ValidationError, match="label_map"):
        _contract_obj(label_map={})
    unlabelled = _contract_obj(label=None, label_map={}, timestamp=None, timestamp_format=None)
    assert unlabelled.has_label is False and _contract_obj().has_label is True


def test_load_contracts_names_the_bad_file(tmp_path):
    (tmp_path / "broken.yaml").write_text("name: other\nversion: 1\n")
    with pytest.raises(ContractError, match="broken.yaml"):
        load_contracts(tmp_path)


def test_load_contracts_needs_name_to_match_file(tmp_path):
    import yaml

    (tmp_path / "renamed.yaml").write_text(yaml.safe_dump(_contract()))
    with pytest.raises(ContractError, match="renamed"):
        load_contracts(tmp_path)
    (tmp_path / "renamed.yaml").rename(tmp_path / "test.yaml")
    assert [c.name for c in load_contracts(tmp_path)] == ["test"]


def test_match_needs_every_required_field_and_prefers_most_columns():
    small = _contract_obj(name="small")
    big = _contract_obj(name="big", known_extras=["Fwd Pkt Len Max"])
    header = [*HEADER, "Fwd Pkt Len Max"]
    assert match_contract(header, [small, big]).contract.name == "big"
    assert match_contract([h for h in HEADER if h != "Dst Port"], [small, big]) is None


def test_match_ignores_spelling_and_order():
    shuffled = [
        " label",
        "DST PORT",
        *[h for h in reversed(HEADER) if h not in ("Label", "Dst Port")],
    ]
    m = match_contract(shuffled, [_contract_obj()])
    assert m.mapping["dst_port"] == "dst_port" and m.mapping["label"] == "label"


def test_match_reports_extras_and_new_columns_in_header_order():
    contract = _contract_obj(known_extras=["Fwd Pkt Len Max"])
    m = match_contract([*HEADER, "Fwd Pkt Len Max", "pkt_entropy", "Geo Country"], [contract])
    assert m.mapping["flow_bytes_per_s"] == "flow_byts_s"
    assert m.extras == ["fwd_pkt_len_max", "pkt_entropy", "geo_country"]
    assert m.new_columns == ["pkt_entropy", "geo_country"]


def test_missing_fields_and_closest_contract():
    header = [h for h in HEADER if h not in ("Dst Port", "Tot Fwd Pkts")]
    assert missing_fields(header, _contract_obj()) == ["dst_port", "fwd_packets"]
    renamed = _contract_obj(name="other", protocol="Proto", flow_duration_us="Duration")
    assert closest_contract(header, [renamed, _contract_obj()]).name == "test"
    assert closest_contract(header, []) is None

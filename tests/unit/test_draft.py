from pathlib import Path

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from app.data.fields import REQUIRED_FIELDS
from pipeline.clean import read_chunks, read_header
from pipeline.contracts import Contract, load_contracts, match_contract
from pipeline.draft import (
    draft_contract,
    guess_timestamp_format,
    propose_mapping,
    quarantine_report,
)
from pipeline.storage import parse_raw_key

TESTS = Path(__file__).resolve().parents[1]
SIM = TESTS / "contracts/broken/simulated-real-traffic-01.csv"
BROKEN = TESTS / "contracts/broken/missing-dst-port.csv"
WED = TESTS / "contracts/cse-cic-ids2018/wednesday-14-02-2018.csv"


def first_chunk(path: Path) -> pd.DataFrame:
    return next(read_chunks(path))


def test_propose_mapping_for_the_simulated_file():
    m = propose_mapping(read_header(SIM), load_contracts())
    assert m["dst_port"] == "Destination Port"
    assert m["fwd_bytes"] == " Total Length of Fwd Packets"
    assert m["flow_packets_per_s"] == " Flow Packets/s" and m["timestamp"] == " Timestamp"
    assert all(m[f] for f in REQUIRED_FIELDS)
    assert (m["label"], m["src_ip"], m["dst_ip"]) == (None, None, None)


def test_similarity_fallback_and_todo():
    m = propose_mapping(["Dest Port", "Protocol", "Weird"], load_contracts())
    assert (m["dst_port"], m["protocol"], m["fwd_packets"]) == ("Dest Port", "Protocol", None)


def test_each_column_is_used_once():
    m = propose_mapping(["Dst Port"], load_contracts())
    assert [f for f, column in m.items() if column] == ["dst_port"]


def test_guess_timestamp_format():
    assert guess_timestamp_format(["14/02/2018 08:31:01", "15/02/2018 23:00:00"]) == (
        "%d/%m/%Y %H:%M:%S"
    )
    assert guess_timestamp_format(["2018-02-16 10:00:00"]) == "%Y-%m-%d %H:%M:%S"
    assert guess_timestamp_format(["yesterday"]) is None and guess_timestamp_format([]) is None


def test_draft_for_the_simulated_file_is_a_valid_contract():
    text = draft_contract(
        "simulated-real-traffic-01", read_header(SIM), load_contracts(), first_chunk(SIM)
    )
    assert text.startswith("#") and "contracts/simulated-real-traffic.yaml" in text
    c = Contract.model_validate(yaml.safe_load(text))
    assert (c.name, c.version, c.timestamp_format, c.has_label) == (
        "simulated-real-traffic",
        1,
        "%Y-%m-%d %H:%M:%S",
        False,
    )
    assert c.fields["fwd_packets"].column == "Total Fwd Packets"
    m = match_contract(read_header(SIM), [c])
    assert m is not None and m.new_columns == []


def test_draft_with_unmapped_fields_is_rejected_until_edited():
    text = draft_contract("x", ["Protocol", "Flow Duration"], load_contracts(), pd.DataFrame())
    assert "dst_port: TODO" in text
    with pytest.raises(ValidationError, match="TODO"):
        Contract.model_validate(yaml.safe_load(text))


def test_draft_label_map_uses_known_categories():
    header = read_header(WED)
    text = draft_contract("cse-cic-ids2018-extra", header, load_contracts(), first_chunk(WED))
    data = yaml.safe_load(text)
    assert data["label_map"] == {"Benign": "Benign", "FTP-BruteForce": "Brute force"}
    assert data["timestamp_format"] == "%d/%m/%Y %H:%M:%S"


def test_report_names_the_missing_field_and_its_expected_column():
    raw = parse_raw_key("raw/broken/missing-dst-port.csv")
    text = quarantine_report(raw, 12, "No contract matches.", read_header(BROKEN), load_contracts())
    assert "#12" in text and "raw/broken/missing-dst-port.csv" in text
    assert 'dst_port: expected "Dst Port" (cse-cic-ids2018 v1)' in text
    assert "draft-contract.yaml" in text


def test_report_lists_columns_no_contract_knows():
    raw = parse_raw_key("raw/simulated-real-traffic-01.csv")
    text = quarantine_report(raw, 3, "No contract matches.", read_header(SIM), load_contracts())
    assert "Destination Port" in text and "pkt_entropy" in text
    assert "Flow Duration" not in text.split("Columns no contract knows")[1]


def test_report_lists_unknown_labels():
    raw = parse_raw_key("raw/cse-cic-ids2018/odd-day.csv")
    header = read_header(WED)
    text = quarantine_report(
        raw, 3, "reason", header, load_contracts(), unknown_labels={"Worm": 40}
    )
    assert "Worm" in text and "40" in text
    assert "Missing required fields" not in text

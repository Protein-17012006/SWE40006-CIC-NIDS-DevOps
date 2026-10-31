"""Data-contract tests (NFR-06): each contract matches its sample files, broken files match none."""

import csv
from pathlib import Path

import pytest
import yaml

from pipeline.clean import read_header
from pipeline.contracts import closest_contract, load_contracts, match_contract, missing_fields

HERE = Path(__file__).parent
BROKEN = HERE / "broken"
SAMPLES = sorted(p for p in HERE.glob("*/*.csv") if p.parent != BROKEN)
EXPECTED = yaml.safe_load((BROKEN / "expected.yaml").read_text(encoding="utf-8"))


def csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))[1:]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_sample_matches_its_contract(sample):
    m = match_contract(read_header(sample), load_contracts())
    assert m is not None and m.contract.name == sample.parent.name and m.new_columns == []


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_broken_file_matches_no_contract(name):
    header = read_header(BROKEN / name)
    assert match_contract(header, load_contracts()) is None
    closest = closest_contract(header, load_contracts())
    assert closest.name == EXPECTED[name]["closest"]
    assert missing_fields(header, closest) == EXPECTED[name]["missing"]


def test_every_broken_file_has_an_expectation():
    assert sorted(p.name for p in BROKEN.glob("*.csv")) == sorted(EXPECTED)


def test_every_contract_has_samples():
    contracts = load_contracts()
    assert contracts
    for c in contracts:
        assert list((HERE / c.name).glob("*.csv")), c.name


def test_baseline_label_map_covers_the_sample_labels():
    contract = next(c for c in load_contracts() if c.name == "cse-cic-ids2018")
    labels = {row[-1].strip() for s in SAMPLES for row in csv_rows(s)}
    assert labels and labels <= set(contract.label_map)

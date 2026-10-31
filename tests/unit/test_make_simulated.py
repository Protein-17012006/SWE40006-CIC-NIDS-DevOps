from pathlib import Path

import pandas as pd
import pytest

from scripts.make_simulated import make_simulated

WED = Path(__file__).resolve().parents[1] / "contracts/cse-cic-ids2018/wednesday-14-02-2018.csv"


def test_renames_drops_label_and_adds_two_columns(tmp_path):
    out = tmp_path / "sim.csv"
    assert make_simulated(WED, out, rows=50) == 50
    df = pd.read_csv(out, dtype=str)
    assert len(df) == 50 and "Label" not in [c.strip() for c in df.columns]
    assert {"Destination Port", " Total Fwd Packets", " pkt_entropy", " geo_country"} <= set(
        df.columns
    )
    assert df.columns[0] == df.columns[0].lstrip()
    assert all(c.startswith(" ") for c in df.columns[1:])
    entropy = df[" pkt_entropy"].astype(float)
    assert entropy.between(0, 8).all() and df[" geo_country"].str.fullmatch("[A-Z]{2}").all()


def test_rewrites_timestamps_in_iso_order(tmp_path):
    make_simulated(WED, tmp_path / "sim.csv", rows=50)
    ts = pd.read_csv(tmp_path / "sim.csv", dtype=str)[" Timestamp"]
    assert ts.str.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}").all()
    assert ts.is_monotonic_increasing and ts.iloc[0].startswith("2018-02-14 ")


def test_keeps_the_source_values_of_sampled_rows(tmp_path):
    make_simulated(WED, tmp_path / "sim.csv", rows=200)
    sim = pd.read_csv(tmp_path / "sim.csv", dtype=str)
    source = pd.read_csv(WED, dtype=str)
    assert sorted(sim["Destination Port"]) == sorted(source["Dst Port"])


def test_is_deterministic_and_refuses_too_many_rows(tmp_path):
    make_simulated(WED, tmp_path / "a.csv", rows=30)
    make_simulated(WED, tmp_path / "b.csv", rows=30)
    make_simulated(WED, tmp_path / "c.csv", rows=30, seed=8)
    assert (tmp_path / "a.csv").read_bytes() == (tmp_path / "b.csv").read_bytes()
    assert (tmp_path / "a.csv").read_bytes() != (tmp_path / "c.csv").read_bytes()
    with pytest.raises(ValueError, match="200"):
        make_simulated(WED, tmp_path / "d.csv", rows=500)

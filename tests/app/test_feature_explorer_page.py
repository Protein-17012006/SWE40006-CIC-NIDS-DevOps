import pytest
from page_helpers import captions

from app.data.fields import ATTACK_CATEGORIES

PAGE = "views/feature_explorer.py"


@pytest.mark.db
def test_feature_explorer_labelled(run_app):
    at = run_app(PAGE)
    assert not at.exception
    options = at.selectbox(key="fx_field").options
    assert "Flow duration (µs)" in options and "fwd_pkt_len_max" in options
    assert "bwd_psh_flags" not in options
    assert at.info[0].value == "Fields kept as extras: bwd_psh_flags, fwd_pkt_len_max."
    summary = at.dataframe[0].value
    assert summary["Category"].tolist() == list(ATTACK_CATEGORIES)
    assert summary["Median"].iloc[0] == "30 ms" and summary["Flows"].iloc[0] == "3.6 k"


@pytest.mark.db
def test_log_scale_caption_mentions_left_out_values(run_app):  # Review Focus 3
    at = run_app(PAGE)
    assert any("values of 0 or less left out" in c for c in captions(at))
    at.toggle(key="fx_log").set_value(False).run()
    assert not at.exception
    assert not any("left out" in c for c in captions(at))


@pytest.mark.db
def test_histogram_and_unlabelled(run_app):
    at = run_app(PAGE)
    at.selectbox(key="fx_chart").select("Histogram").run()
    assert not at.exception and len(at.get("plotly_chart")) == 1
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert not at.exception
    options = at.selectbox(key="fx_field").options
    assert "pkt_entropy" in options and "geo_country" not in options
    assert at.dataframe[0].value["Category"].tolist() == ["All traffic"]

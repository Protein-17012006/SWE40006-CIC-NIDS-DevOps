import pytest
from page_helpers import captions

PAGE = "views/targets.py"


@pytest.mark.db
def test_targets_labelled(run_app):
    at = run_app(PAGE)
    assert not at.exception
    assert at.caption[0].value.endswith("· 6 attack categories selected")
    assert at.info[0].value == (
        'Ports outside the top 50 per day, category and protocol are counted together as "other".'
    )
    table = at.dataframe[0].value
    assert table.iloc[0].tolist() == ["DoS", "80 · HTTP", "100.0 %", "—"]
    assert table.set_index("Category").loc["DDoS", "Next port"] == "53 · DNS (0.5 %)"
    assert len(at.get("plotly_chart")) == 2


@pytest.mark.db
def test_targets_one_category(run_app):  # the UI-04 acceptance check
    at = run_app(PAGE, {"filter_categories": ["DDoS"]})
    assert not at.exception
    assert at.caption[0].value.endswith("· 1 attack category selected")
    assert at.dataframe[0].value["Category"].tolist() == ["DDoS"]


@pytest.mark.db
def test_targets_unlabelled(run_app):
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert not at.exception
    assert at.caption[0].value == (
        "Destination ports and protocols of all traffic · this dataset has no label"
    )
    assert "Hidden: this chart needs the label field." in captions(at)
    assert "All traffic · linear scale" in captions(at)

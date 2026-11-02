import pytest
from page_helpers import captions, markdown, tiles, x_axis

from app.components.layout import NO_FLOWS

PAGE = "views/overview.py"


@pytest.mark.db
def test_overview_labelled(run_app):
    at = run_app(PAGE)
    assert not at.exception
    assert tiles(at) == {
        "Flows": "7.16 k",
        "Attack share": "49.7 %",
        "Attack types": "7",
        "Capture days": "2",
    }
    assert {
        "2 capture days",
        "3.56 k attack flows",
        "in 6 categories",
        "14 Feb – 21 Feb 2018",
    } <= set(captions(at))
    assert at.caption[0].value.startswith("cse-cic-ids2018 · 7.16 k flows · 2 capture days")
    assert {"**Flows by category**", "**Top attack labels**", "**Attack mix**"} <= markdown(at)
    assert len(at.get("plotly_chart")) == 2 and len(at.dataframe) == 1
    assert at.dataframe[0].value.iloc[0].tolist() == ["DDOS attack-HOIC", "DDoS", "2 k", "56.3 %"]


@pytest.mark.db
def test_overview_unlabelled(run_app):
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert not at.exception
    assert tiles(at) == {
        "Flows": "1 k",
        "Attack share": "—",
        "Attack types": "—",
        "New columns": "2",
    }
    assert at.info[0].value == (
        "This file has no label column, so the attack-category charts are hidden. "
        "Traffic charts still work, and the 2 new columns appear in the Feature explorer."
    )
    assert "pkt_entropy, geo_country" in captions(at)
    assert captions(at).count("Hidden: this chart needs the label field.") == 2
    assert {"**Flows per hour**", "**Top destination ports**"} <= markdown(at)
    hours = x_axis(at.get("plotly_chart")[0])  # Flows per hour
    assert hours.get("tickvals") == [f"{h:02d}:00" for h in range(0, 24, 3)]


@pytest.mark.db
def test_overview_with_no_categories(run_app):  # Review Focus 4
    at = run_app(PAGE, {"filter_categories": []})
    assert not at.exception
    assert [i.value for i in at.info].count(NO_FLOWS) == 2
    assert len(at.get("plotly_chart")) == 1  # Flows by category: Benign only

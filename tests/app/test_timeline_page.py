from datetime import date

import pytest
from page_helpers import captions, markdown

PAGE = "views/timeline.py"


@pytest.mark.db
def test_timeline_defaults_to_the_busiest_attack_day(run_app):
    at = run_app(PAGE)
    assert not at.exception
    assert at.selectbox(key="timeline_day").value == date(2018, 2, 21)
    assert "**Flows per hour on 21 Feb 2018**" in markdown(at)
    assert "DDOS attack-HOIC sent 2 k flows between 14:00 and 15:00" in captions(at)
    assert "Each capture day carries one attack campaign · 21 Feb selected" in captions(at)
    assert at.dataframe[0].value.iloc[0].tolist() == ["21 Feb", "14:00", "2.2 k", "DDoS"]
    assert len(at.get("plotly_chart")) == 2


@pytest.mark.db
def test_timeline_follows_the_day_picker(run_app):
    at = run_app(PAGE)
    at.selectbox(key="timeline_day").select(date(2018, 2, 14)).run()
    assert not at.exception
    assert "**Flows per hour on 14 Feb 2018**" in markdown(at)
    assert "Benign sent 1 k flows between 10:00 and 11:00" in captions(at)


@pytest.mark.db
def test_timeline_unlabelled(run_app):
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert not at.exception
    assert "Hidden: this chart needs the label field." in captions(at)
    assert at.selectbox(key="timeline_day").options == ["2 Mar 2018"]
    assert "Peak: 500 flows between 10:00 and 11:00" in captions(at)
    assert "Main category" not in at.dataframe[0].value.columns


@pytest.mark.db
def test_stale_day_is_replaced_on_screen(run_app):  # a day picked on another dataset
    at = run_app(
        PAGE, {"filter_dataset": "simulated-real-traffic-01", "timeline_day": date(2018, 2, 14)}
    )
    picker = at.selectbox(key="timeline_day")
    assert not at.exception
    assert picker.value == date(2018, 3, 2) and picker.proto.set_value
    assert "**Flows per hour on 2 Mar 2018**" in markdown(at)

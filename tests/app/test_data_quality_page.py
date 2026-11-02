import pytest
from page_helpers import captions, markdown, tiles

PAGE = "views/data_quality.py"


@pytest.mark.db
def test_data_quality_labelled(run_app):
    at = run_app(PAGE)
    assert not at.exception
    assert tiles(at) == {
        "Rows read": "7.3 k",
        "Rows rejected": "45",
        "Duplicates removed": "100",
        "Infinite values replaced": "20",
    }
    assert {"2 files", "0 quarantined files", "1.4 % of rows read", "1 column"} <= set(captions(at))
    assert at.caption[0].value == (
        "What the cleaning step changed in cse-cic-ids2018 · ingestion runs #1 to #3"
        " · uses only the Dataset filter"
    )
    assert at.warning[0].value == (
        "1 column holds one value in every row and is hidden from the Feature explorer: "
        "bwd_psh_flags."
    )
    assert {"**Rows changed by each cleaning step**", "**Columns needing attention**"} <= markdown(
        at
    )
    columns = at.dataframe[0].value
    assert columns["Column"].tolist() == ["flow_bytes_per_s", "bwd_psh_flags"]
    files = at.dataframe[-1].value
    assert files["Columns"].tolist() == ["15", "15"]
    assert files["Rows"].tolist() == ["3,500", "3,800"]


@pytest.mark.db
def test_data_quality_ignores_dates_and_categories(run_app):
    at = run_app(PAGE, {"filter_categories": ["DDoS"]})
    assert tiles(at)["Rows read"] == "7.3 k"


@pytest.mark.db
def test_data_quality_unlabelled(run_app):
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert not at.exception
    assert at.dataframe[-1].value["Columns"].tolist() == ["10 (2 new, kept)"]
    assert "The cleaning step changed no rows." in [i.value for i in at.info]
    assert len(at.warning) == 0

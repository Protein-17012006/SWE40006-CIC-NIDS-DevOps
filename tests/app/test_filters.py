from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app.components.filters import CATEGORIES_KEY, DATASET_KEY, DATES_KEY, current_filters
from app.data.fields import ATTACK_ONLY

MAIN = str(Path(__file__).resolve().parents[2] / "app" / "main.py")

# What loaded_datasets() returns for the seeded fixture
DATASETS = pd.DataFrame(
    [
        {
            "dataset_id": "cse-cic-ids2018",
            "display_name": "cse-cic-ids2018",
            "has_label": True,
            "fields": ["timestamp", "dst_port", "protocol", "label", "attack_category"],
            "extra_fields": ["bwd_psh_flags", "fwd_pkt_len_max"],
            "row_count": 7155,
            "first_ts": pd.Timestamp("2018-02-14 09:00"),
            "last_ts": pd.Timestamp("2018-02-21 16:59"),
            "loaded_at": pd.Timestamp(datetime(2026, 11, 2, 8, 0, tzinfo=UTC)),
        },
        {
            "dataset_id": "simulated-real-traffic-01",
            "display_name": "simulated-real-traffic-01",
            "has_label": False,
            "fields": ["timestamp", "dst_port", "protocol"],
            "extra_fields": ["pkt_entropy", "geo_country"],
            "row_count": 1000,
            "first_ts": pd.Timestamp("2018-03-02 09:00"),
            "last_ts": pd.Timestamp("2018-03-02 11:59"),
            "loaded_at": pd.Timestamp(datetime(2026, 11, 2, 8, 1, tzinfo=UTC)),
        },
    ]
)


def test_defaults_to_baseline_full_span_all_categories():
    f = current_filters(DATASETS, {})
    assert (f.dataset_id, f.date_from, f.date_to) == (
        "cse-cic-ids2018",
        date(2018, 2, 14),
        date(2018, 2, 21),
    )
    assert f.categories == ATTACK_ONLY
    assert f.extra_fields == ("bwd_psh_flags", "fwd_pkt_len_max") and f.row_count == 7155


def test_single_date_counts_as_one_day():  # Review Focus 1
    f = current_filters(DATASETS, {DATES_KEY: (date(2018, 2, 21),)})
    assert f.date_from == f.date_to == date(2018, 2, 21)


def test_dates_outside_the_span_fall_back_to_the_span():
    f = current_filters(DATASETS, {DATES_KEY: (date(2018, 3, 1), date(2018, 3, 2))})
    assert (f.date_from, f.date_to) == (date(2018, 2, 14), date(2018, 2, 21))


def test_empty_category_list_means_none():
    assert current_filters(DATASETS, {CATEGORIES_KEY: []}).categories == ()
    assert current_filters(DATASETS, {CATEGORIES_KEY: ["DDoS", "Benign"]}).categories == ("DDoS",)


def test_unlabelled_dataset_has_no_categories():
    f = current_filters(
        DATASETS, {DATASET_KEY: "simulated-real-traffic-01", CATEGORIES_KEY: ["DDoS"]}
    )
    assert f.has_label is False and f.categories == ()


def test_no_loaded_dataset():
    assert current_filters(DATASETS.iloc[0:0], {}) is None


@pytest.mark.db
def test_sidebar_draws_filters(run_app):
    at = run_app("main.py")
    assert not at.exception
    assert at.selectbox(key=DATASET_KEY).options == [
        "cse-cic-ids2018",
        "simulated-real-traffic-01",
    ]
    assert at.multiselect(key=CATEGORIES_KEY).value == list(ATTACK_ONLY)
    assert at.date_input(key=DATES_KEY).value == (date(2018, 2, 14), date(2018, 2, 21))
    assert "FILTERS" in [c.value for c in at.sidebar.caption]


@pytest.mark.db
def test_changing_dataset_resets_dates_and_categories(run_app):  # Review Focus 2
    at = run_app("main.py")
    at.multiselect(key=CATEGORIES_KEY).set_value(["DDoS"]).run()
    at.selectbox(key=DATASET_KEY).select("simulated-real-traffic-01").run()
    assert not at.exception
    assert at.date_input(key=DATES_KEY).value == (date(2018, 3, 2), date(2018, 3, 2))
    assert at.multiselect(key=CATEGORIES_KEY).disabled
    at.selectbox(key=DATASET_KEY).select("cse-cic-ids2018").run()
    assert at.multiselect(key=CATEGORIES_KEY).value == list(ATTACK_ONLY)


def test_sidebar_without_database(settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    clear_caches()
    at = AppTest.from_file(MAIN, default_timeout=30).run()
    assert not at.exception and len(at.sidebar.selectbox) == 0

from streamlit.testing.v1 import AppTest

from app.components.layout import CARD_FAILED, NO_FLOWS

# Each card function is module-level and imports what it uses inside its body, because
# AppTest.from_function runs only the function's source.


def run(fn) -> AppTest:
    return AppTest.from_function(fn).run()


def card_needing_label_on_unlabelled_filters():
    from datetime import date

    from app.components.filters import Filters
    from app.components.layout import chart_card

    def load():
        raise AssertionError("a hidden card must not load its data")

    unlabelled = Filters(
        dataset_id="simulated-real-traffic-01",
        display_name="simulated-real-traffic-01",
        has_label=False,
        fields=("timestamp", "dst_port"),
        extra_fields=(),
        date_from=date(2018, 3, 2),
        date_to=date(2018, 3, 2),
        categories=(),
        row_count=1000,
        loaded_at=None,
    )
    chart_card("Flows by category", "Log scale", load, print, filters=unlabelled, needs=("label",))


def card_whose_load_raises():
    from app.components.layout import chart_card

    def load():
        raise RuntimeError("relation agg_hourly does not exist\nLINE 1: SELECT ...")

    chart_card("Flows by category", "Log scale", load, print)


def card_with_empty_frame():
    import pandas as pd

    from app.components.layout import chart_card

    chart_card("Attack mix", "Share", lambda: pd.DataFrame({"flows": []}), print)


def card_with_two_rows():
    import pandas as pd
    import streamlit as st

    from app.components.layout import chart_card

    def load():
        return pd.DataFrame({"label": ["Bot", "Infilteration"], "flows": [200, 50]})

    chart_card("Top attack labels", lambda df: f"{len(df)} labels", load, st.dataframe)


def test_card_hidden_when_field_missing():
    at = run(card_needing_label_on_unlabelled_filters)
    assert not at.exception
    assert at.caption[0].value == "Hidden: this chart needs the label field."
    assert "**Flows by category**" in [m.value for m in at.markdown]


def test_failed_query_warns_and_logs(capsys):
    at = run(card_whose_load_raises)
    assert at.warning[0].value == CARD_FAILED
    out = capsys.readouterr().out
    assert '"event": "query_failed"' in out and '"card": "Flows by category"' in out
    assert "LINE 1" not in out


def test_empty_data_says_no_flows():
    at = run(card_with_empty_frame)
    assert at.info[0].value == NO_FLOWS and len(at.download_button) == 0


def test_card_offers_csv_and_a_caption_from_the_data():
    at = run(card_with_two_rows)
    assert at.download_button[0].label == "CSV"
    assert at.caption[0].value == "2 labels" and len(at.dataframe) == 1

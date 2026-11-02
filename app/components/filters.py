"""The sidebar filters every page shares (UI-01): dataset, date range and attack categories.

The selection lives in session state under three keys. current_filters checks it against the
loaded datasets, so a page never sees a dataset that is gone or dates outside its span.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import streamlit as st

from app.data.fields import ATTACK_ONLY
from app.data.queries import loaded_datasets
from app.telemetry import log_event

DATASET_KEY = "filter_dataset"
DATES_KEY = "filter_dates"
CATEGORIES_KEY = "filter_categories"

DB_DOWN = "The database cannot be reached. The Pipeline page shows the connection status."
NO_DATA = 'No dataset is loaded yet. The runbook\'s "Load data" section explains how to load one.'


@dataclass(frozen=True)
class Filters:
    dataset_id: str
    display_name: str
    has_label: bool
    fields: tuple[str, ...]
    extra_fields: tuple[str, ...]
    date_from: date | None
    date_to: date | None
    categories: tuple[str, ...]
    row_count: int
    loaded_at: datetime | None


def _day(value: object) -> date | None:
    return None if value is None or pd.isna(value) else pd.Timestamp(value).date()


def _span(row: pd.Series) -> tuple[date | None, date | None]:
    return _day(row["first_ts"]), _day(row["last_ts"])


def _picked_dates(value: object) -> tuple[date, date] | None:
    """A date_input range: two dates, or one while the viewer is still picking the end."""
    if isinstance(value, date):
        return value, value
    if isinstance(value, tuple | list) and value:
        return value[0], value[-1]
    return None


def _chosen_row(datasets: pd.DataFrame, state: Mapping[str, object]) -> pd.Series:
    ids = datasets["dataset_id"].tolist()
    chosen = state.get(DATASET_KEY)
    return datasets.iloc[ids.index(chosen) if chosen in ids else 0]


def current_filters(datasets: pd.DataFrame, state: Mapping[str, object]) -> Filters | None:
    """The viewer's selection, with defaults wherever it is missing or no longer fits."""
    if datasets.empty:
        return None
    row = _chosen_row(datasets, state)
    first, last = _span(row)
    date_from, date_to = first, last
    picked = _picked_dates(state.get(DATES_KEY))
    if first is not None and last is not None and picked is not None:
        start, end = max(picked[0], first), min(picked[1], last)
        if start <= end:
            date_from, date_to = start, end
    has_label = bool(row["has_label"])
    if not has_label:
        categories: tuple[str, ...] = ()
    elif CATEGORIES_KEY in state:
        chosen = state[CATEGORIES_KEY] or ()
        categories = tuple(c for c in ATTACK_ONLY if c in chosen)
    else:
        categories = ATTACK_ONLY
    loaded_at = row["loaded_at"]
    return Filters(
        dataset_id=row["dataset_id"],
        display_name=row["display_name"],
        has_label=has_label,
        fields=tuple(row["fields"] or ()),
        extra_fields=tuple(row["extra_fields"] or ()),
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        row_count=int(row["row_count"]),
        loaded_at=None if pd.isna(loaded_at) else pd.Timestamp(loaded_at).to_pydatetime(),
    )


def _first_line(exc: Exception) -> str:
    text = str(exc)
    return text.splitlines()[0] if text else type(exc).__name__


def _datasets_or_none() -> pd.DataFrame | None:
    try:
        return loaded_datasets()
    except Exception as exc:  # unreachable, or not migrated yet
        log_event("query_failed", level="ERROR", query="loaded_datasets", message=_first_line(exc))
        return None


def _reset_selection() -> None:
    """A new dataset starts from its own full span and every category."""
    st.session_state.pop(DATES_KEY, None)
    st.session_state.pop(CATEGORIES_KEY, None)


def _drop_stale_state(datasets: pd.DataFrame) -> None:
    """Widgets raise on a stored value outside their options; drop such values first."""
    state = st.session_state
    if state.get(DATASET_KEY) not in datasets["dataset_id"].tolist():
        state.pop(DATASET_KEY, None)
    first, last = _span(_chosen_row(datasets, state))
    picked = _picked_dates(state.get(DATES_KEY))
    if picked is not None and not (first and last and first <= picked[0] <= picked[1] <= last):
        state.pop(DATES_KEY, None)
    if CATEGORIES_KEY in state:
        state[CATEGORIES_KEY] = [c for c in state[CATEGORIES_KEY] or () if c in ATTACK_ONLY]


def sidebar_filters() -> None:
    """Draw the filters under the page links; draw nothing without a loaded dataset."""
    datasets = _datasets_or_none()
    if datasets is None or datasets.empty:
        return
    _drop_stale_state(datasets)
    names = dict(zip(datasets["dataset_id"], datasets["display_name"], strict=True))
    with st.sidebar:
        st.caption("FILTERS")
        st.selectbox(
            "Dataset",
            list(names),
            format_func=names.__getitem__,
            key=DATASET_KEY,
            on_change=_reset_selection,
        )
        f = current_filters(datasets, st.session_state)
        first, last = _span(_chosen_row(datasets, st.session_state))
        if first is not None and last is not None:
            value = {} if DATES_KEY in st.session_state else {"value": (first, last)}
            st.date_input("Date range", min_value=first, max_value=last, key=DATES_KEY, **value)
        default = {} if CATEGORIES_KEY in st.session_state else {"default": list(ATTACK_ONLY)}
        st.multiselect(
            "Attack categories",
            ATTACK_ONLY,
            key=CATEGORIES_KEY,
            disabled=not f.has_label,
            **default,
        )
        if not f.has_label:
            st.caption("This dataset has no label.")


def page_filters() -> Filters:
    """The filters for a page; stops the page with a message when there is nothing to show."""
    datasets = _datasets_or_none()
    if datasets is None:
        st.error(DB_DOWN)
        st.stop()
    f = current_filters(datasets, st.session_state)
    if f is None:
        st.info(NO_DATA)
        st.stop()
    return f

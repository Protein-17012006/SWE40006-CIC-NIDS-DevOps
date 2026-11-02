"""Shared page furniture: environment banner, sidebar brand and footer, headers, tiles, cards."""

import re
from collections.abc import Callable, Sequence

import pandas as pd
import streamlit as st

from app.components.filters import Filters
from app.components.guard import missing
from app.config import Settings
from app.telemetry import first_line, log_event

NO_FLOWS = "No flows match the filters."
CARD_FAILED = "This card could not load its data. The logs have the error."
HIDDEN = "Hidden: this chart needs the {field} field."


def env_banner(settings: Settings) -> None:
    """Every environment except production says which one it is (UI-10)."""
    if not settings.is_production:
        st.warning(
            f"{settings.app_env.upper()} environment · version {settings.app_version}"
            " · not production data"
        )


def sidebar_brand() -> None:
    st.sidebar.markdown(":material/shield: **CIC-NIDS Dashboard**")
    st.sidebar.caption("Network intrusion analytics")


def sidebar_footer(settings: Settings) -> None:
    st.sidebar.caption(f"{settings.app_env} · version {settings.app_version}")


def page_header(title: str, caption: str | None = None) -> None:
    st.title(title)
    if caption:
        st.caption(caption)


def kpi_tile(label: str, value: str, caption: str) -> None:
    with st.container(border=True):
        st.metric(label, value)
        st.caption(caption)


def load_or_warn(what: str, load: Callable[[], pd.DataFrame]) -> pd.DataFrame | None:
    """Run one of the page's queries; on failure log it, show CARD_FAILED and return None."""
    try:
        return load()
    except Exception as exc:
        log_event("query_failed", level="ERROR", card=what, message=first_line(exc))
        st.warning(CARD_FAILED)
        return None


def _card_title(title: str) -> None:
    st.markdown(f"**{title}**")


def hidden_card(title: str, field: str) -> None:
    """The card a chart leaves when the dataset lacks a field it needs (UI-08)."""
    with st.container(border=True):
        _card_title(title)
        st.caption(HIDDEN.format(field=field))


def chart_card(
    title: str,
    caption: str | Callable[[pd.DataFrame], str],
    load: Callable[[], pd.DataFrame],
    render: Callable[[pd.DataFrame], None],
    *,
    filters: Filters | None = None,
    needs: Sequence[str] = (),
    csv: bool = True,
    empty: str = NO_FLOWS,
) -> None:
    """A bordered card: hidden without a needed field, a warning when its query fails,
    the empty note when nothing matches, else the caption, the visual and its data as CSV
    (UI-11)."""
    lacking = missing(filters, needs) if filters is not None else []
    if lacking:
        hidden_card(title, lacking[0])
        return
    with st.container(border=True):
        head = st.container(
            horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
        )
        with head:
            _card_title(title)
        frame = load_or_warn(title, load)
        if frame is None:
            return
        if frame.empty:
            st.info(empty)
            return
        st.caption(caption(frame) if callable(caption) else caption)
        render(frame)
        if csv:
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            with head:
                st.download_button(
                    "CSV",
                    frame.to_csv(index=False),
                    file_name=f"{slug}.csv",
                    mime="text/csv",
                    key=f"csv-{slug}",
                    type="tertiary",
                    icon=":material/download:",
                )

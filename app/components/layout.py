"""Shared page furniture: environment banner, sidebar brand and footer, headers, KPI tiles."""

import streamlit as st

from app.config import Settings


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


def coming_soon(requirement_ids: str) -> None:
    st.info(f"This page arrives in a later release ({requirement_ids}).")

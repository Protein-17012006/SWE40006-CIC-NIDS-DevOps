"""One query function per visual. Each returns a DataFrame and is cached for five minutes."""

import pandas as pd
import sqlalchemy as sa
import streamlit as st

from app.data.db import get_engine


def _read(query: str, **params: object) -> pd.DataFrame:
    engine = get_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is not set")
    with engine.connect() as conn:
        return pd.read_sql_query(sa.text(query), conn, params=params)


@st.cache_data(ttl=300)
def last_ingestion_run() -> pd.DataFrame:
    return _read("SELECT run_id, started_at FROM ingestion_runs ORDER BY run_id DESC LIMIT 1")

"""The dashboard's database engine and a cheap health check."""

import time
from dataclasses import dataclass

import sqlalchemy as sa
import streamlit as st

from app.config import get_settings


@dataclass(frozen=True)
class PingResult:
    ok: bool
    latency_ms: int | None
    server_version: str | None
    error: str | None


def make_engine(database_url: str) -> sa.Engine:
    return sa.create_engine(
        database_url, pool_pre_ping=True, pool_size=5, connect_args={"connect_timeout": 3}
    )


@st.cache_resource
def get_engine() -> sa.Engine | None:
    url = get_settings().database_url
    return make_engine(url) if url else None


def ping(engine: sa.Engine | None) -> PingResult:
    """SELECT 1 and the server version; the error names the failure, never the credentials."""
    if engine is None:
        return PingResult(False, None, None, "DATABASE_URL is not set")
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
            latency_ms = int((time.perf_counter() - started) * 1000)
            version = conn.execute(sa.text("SHOW server_version")).scalar_one()
    except sa.exc.SQLAlchemyError as exc:
        return PingResult(False, None, None, _describe(exc))
    return PingResult(True, latency_ms, str(version).split()[0], None)


def _describe(exc: sa.exc.SQLAlchemyError) -> str:
    original = getattr(exc, "orig", None) or exc
    text = str(original)
    return f"{type(original).__name__}: {text.splitlines()[0] if text else ''}"

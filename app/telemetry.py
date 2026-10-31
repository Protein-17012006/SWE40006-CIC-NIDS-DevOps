"""JSON log lines on stdout and page render timing (NFR-05)."""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.config import get_settings

SENSITIVE_KEYS = frozenset(
    {"password", "database_url", "db_secret", "db_master_secret", "upload_password"}
)


def _env_and_version() -> tuple[str, str]:
    try:
        settings = get_settings()
    except ValueError:
        return "unknown", "unknown"
    return settings.app_env, settings.app_version


def log_event(event: str, *, level: str = "INFO", **fields: object) -> dict[str, object]:
    """Print one JSON object on one line of stdout; fields named like secrets are dropped."""
    env, version = _env_and_version()
    now = datetime.now(UTC)
    record: dict[str, object] = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
        "level": level,
        "env": env,
        "version": version,
        "event": event,
    }
    record.update({k: v for k, v in fields.items() if k.lower() not in SENSITIVE_KEYS})
    print(json.dumps(record, default=str), flush=True)
    return record


@contextmanager
def page_render(page: str) -> Iterator[None]:
    """Log how long one page run took. st.stop and st.rerun are BaseExceptions, not errors."""
    started = time.perf_counter()
    level = "INFO"
    try:
        yield
    except Exception:
        level = "ERROR"
        raise
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        log_event("page_render", level=level, page=page, duration_ms=duration_ms)

"""What the dashboard reads from its environment's bucket: quarantine reports and drafts."""

from app.config import get_settings
from app.telemetry import first_line, log_event
from pipeline.storage import Bucket


def has_bucket() -> bool:
    """False on a laptop, where S3_BUCKET is not set."""
    return get_settings().s3_bucket is not None


def read_text(key: str) -> str | None:
    """The object's text, or None without a bucket or when it cannot be read (logged)."""
    name = get_settings().s3_bucket
    if name is None:
        return None
    try:
        return Bucket(name).read_text(key)
    except Exception as exc:  # a missing key, a denied read, or no network
        log_event("s3_read_failed", level="WARNING", key=key, message=first_line(exc))
        return None

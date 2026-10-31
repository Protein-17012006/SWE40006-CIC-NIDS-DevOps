"""Settings from environment variables, read once per process (deployment contract)."""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from urllib.parse import quote

APP_ENVS: tuple[str, ...] = ("local", "development", "test", "staging", "production")
_SECRET_KEYS = ("username", "password", "host", "port", "dbname")


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_version: str
    aws_region: str
    s3_bucket: str | None
    database_url: str | None
    upload_password: str | None
    started_at: datetime

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def database_url_from_secret(secret_json: str) -> str:
    """Build a SQLAlchemy URL from a secret holding username, password, host, port and dbname."""
    secret = json.loads(secret_json)
    missing = [key for key in _SECRET_KEYS if key not in secret]
    if missing:
        raise ValueError(f"DB_SECRET is missing: {', '.join(missing)}")
    user = quote(str(secret["username"]), safe="")
    password = quote(str(secret["password"]), safe="")
    host, port, dbname = secret["host"], secret["port"], secret["dbname"]
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    app_env = env.get("APP_ENV") or "local"
    if app_env not in APP_ENVS:
        raise ValueError(f"APP_ENV must be one of {', '.join(APP_ENVS)}; got {app_env!r}")
    database_url = env.get("DATABASE_URL") or None
    if database_url is None and env.get("DB_SECRET"):
        database_url = database_url_from_secret(env["DB_SECRET"])
    return Settings(
        app_env=app_env,
        app_version=env.get("APP_VERSION") or "unknown",
        aws_region=env.get("AWS_REGION") or "us-east-1",
        s3_bucket=env.get("S3_BUCKET") or None,
        database_url=database_url,
        upload_password=env.get("UPLOAD_PASSWORD") or None,
        started_at=datetime.now(UTC),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()

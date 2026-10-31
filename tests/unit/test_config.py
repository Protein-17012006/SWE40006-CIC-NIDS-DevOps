import json
from datetime import UTC

import pytest

from app.config import database_url_from_secret, load_settings


def test_defaults_when_environment_is_empty():
    s = load_settings({})
    assert (s.app_env, s.app_version, s.aws_region) == ("local", "unknown", "us-east-1")
    assert s.s3_bucket is None and s.database_url is None and s.upload_password is None
    assert s.started_at.tzinfo is UTC
    assert s.is_production is False


def test_reads_every_variable():
    s = load_settings(
        {
            "APP_ENV": "production",
            "APP_VERSION": "3f2a9c1",
            "S3_BUCKET": "b",
            "DATABASE_URL": "postgresql+psycopg://a:b@h:5432/d",
            "UPLOAD_PASSWORD": "pw",
        }
    )
    assert (s.app_env, s.app_version, s.s3_bucket, s.upload_password) == (
        "production",
        "3f2a9c1",
        "b",
        "pw",
    )
    assert s.database_url == "postgresql+psycopg://a:b@h:5432/d" and s.is_production


def test_rejects_unknown_app_env():
    with pytest.raises(ValueError, match="APP_ENV must be one of"):
        load_settings({"APP_ENV": "prod"})


def test_empty_s3_bucket_is_none():
    assert load_settings({"S3_BUCKET": ""}).s3_bucket is None


def test_database_url_built_from_secret_with_quoted_password():
    secret = json.dumps(
        {
            "username": "cicnids_staging",
            "password": "p@ss/w:rd%",
            "host": "db.example",
            "port": 5432,
            "dbname": "cicnids_staging",
        }
    )
    assert database_url_from_secret(secret) == (
        "postgresql+psycopg://cicnids_staging:p%40ss%2Fw%3Ard%25@db.example:5432/cicnids_staging"
    )


def test_db_secret_used_only_without_database_url():
    secret = json.dumps(
        {"username": "u", "password": "p", "host": "h", "port": 5432, "dbname": "d"}
    )
    assert load_settings({"DB_SECRET": secret}).database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert load_settings({"DB_SECRET": secret, "DATABASE_URL": "x"}).database_url == "x"


def test_secret_missing_key_is_named():
    with pytest.raises(ValueError, match="host"):
        database_url_from_secret(
            json.dumps({"username": "u", "password": "p", "port": 5432, "dbname": "d"})
        )

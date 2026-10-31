"""Commands for the one-off ECS tasks: python -m pipeline <command>."""

import argparse
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

import sqlalchemy as sa

from app.config import get_settings
from app.telemetry import log_event
from pipeline import dbadmin, migrate


def _database_url() -> str:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL (or DB_SECRET) is not set")
    return url


def _bucket_name() -> str:
    name = get_settings().s3_bucket
    if not name:
        raise RuntimeError("S3_BUCKET is not set")
    return name


def _migrate(args: argparse.Namespace) -> str:
    migrate.upgrade(_database_url())
    return "database is at the latest revision"


def _db_bootstrap(args: argparse.Namespace) -> str:
    master, app_secret = os.environ.get("DB_MASTER_SECRET"), os.environ.get("DB_SECRET")
    if not master or not app_secret:
        raise RuntimeError("DB_MASTER_SECRET and DB_SECRET must both be set")
    result = dbadmin.bootstrap(master, app_secret)
    return f"role created: {result.role_created}, database created: {result.database_created}"


def _ingest(args: argparse.Namespace) -> str:
    # Imported here, so migrate and db-bootstrap do not load pandas, pandera and boto3
    from pipeline.contracts import load_contracts
    from pipeline.ingest import ingest_file
    from pipeline.storage import Bucket

    url, bucket_name = _database_url(), _bucket_name()
    engine = sa.create_engine(url, pool_pre_ping=True)
    try:
        with tempfile.TemporaryDirectory() as workdir:
            record = ingest_file(
                args.key,
                engine=engine,
                bucket=Bucket(bucket_name),
                contracts=load_contracts(),
                commit_sha=get_settings().app_version,
                workdir=Path(workdir),
            )
    finally:
        engine.dispose()
    return record.message if record else f"skipped {args.key}: not a CSV file under raw/"


COMMANDS: dict[str, tuple[str, Callable[[argparse.Namespace], str]]] = {
    "migrate": ("apply every Alembic migration (alembic upgrade head)", _migrate),
    "db-bootstrap": (
        "create or update this environment's database role and database",
        _db_bootstrap,
    ),
    "ingest": ("ingest one file from the environment bucket", _ingest),
}


def _add_arguments(name: str, parser: argparse.ArgumentParser) -> None:
    if name == "ingest":
        parser.add_argument("--key", required=True, help="the S3 key, under raw/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline", description="CIC-NIDS one-off tasks"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (help_text, _) in COMMANDS.items():
        _add_arguments(name, commands.add_parser(name, help=help_text))
    args = parser.parse_args(argv)
    _, run = COMMANDS[args.command]
    try:
        message = run(args)
    except Exception as exc:  # every failure becomes one log line and exit code 1
        log_event(args.command, level="ERROR", status="failed", message=str(exc))
        return 1
    log_event(args.command, status="ok", message=message)
    return 0

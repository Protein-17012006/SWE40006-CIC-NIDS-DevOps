"""Commands for the one-off ECS tasks: python -m pipeline <command>."""

import argparse
import os
from collections.abc import Callable

from app.config import get_settings
from app.telemetry import log_event
from pipeline import dbadmin, migrate


def _migrate() -> str:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL (or DB_SECRET) is not set")
    migrate.upgrade(url)
    return "database is at the latest revision"


def _db_bootstrap() -> str:
    master, app_secret = os.environ.get("DB_MASTER_SECRET"), os.environ.get("DB_SECRET")
    if not master or not app_secret:
        raise RuntimeError("DB_MASTER_SECRET and DB_SECRET must both be set")
    result = dbadmin.bootstrap(master, app_secret)
    return f"role created: {result.role_created}, database created: {result.database_created}"


COMMANDS: dict[str, tuple[str, Callable[[], str]]] = {
    "migrate": ("apply every Alembic migration (alembic upgrade head)", _migrate),
    "db-bootstrap": (
        "create or update this environment's database role and database",
        _db_bootstrap,
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline", description="CIC-NIDS one-off tasks"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (help_text, _) in COMMANDS.items():
        commands.add_parser(name, help=help_text)
    args = parser.parse_args(argv)
    _, run = COMMANDS[args.command]
    try:
        message = run()
    except Exception as exc:  # every failure becomes one log line and exit code 1
        log_event(args.command, level="ERROR", status="failed", message=str(exc))
        return 1
    log_event(args.command, status="ok", message=message)
    return 0

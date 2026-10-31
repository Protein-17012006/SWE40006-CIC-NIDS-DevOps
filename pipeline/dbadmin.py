"""Create each environment's database role and database, using the RDS master user."""

import json
import re
from dataclasses import dataclass

import psycopg
from psycopg import sql

IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class BootstrapResult:
    role_created: bool
    database_created: bool


def _load(secret_json: str, keys: tuple[str, ...], name: str) -> dict:
    secret = json.loads(secret_json)
    missing = [key for key in keys if key not in secret]
    if missing:
        raise ValueError(f"{name} is missing: {', '.join(missing)}")
    return secret


def bootstrap(
    master_secret_json: str, app_secret_json: str, *, master_database: str = "postgres"
) -> BootstrapResult:
    """Idempotent: creates the role and database when missing and syncs the role's password."""
    master = _load(master_secret_json, ("username", "password"), "DB_MASTER_SECRET")
    app = _load(app_secret_json, ("username", "password", "host", "port", "dbname"), "DB_SECRET")
    for key in ("username", "dbname"):
        if not IDENTIFIER_RE.match(str(app[key])):
            raise ValueError(f"DB_SECRET {key} is not a safe identifier: {app[key]!r}")

    role, database = sql.Identifier(app["username"]), sql.Identifier(app["dbname"])
    password = sql.Literal(str(app["password"]))
    step = "connecting"
    try:
        with psycopg.connect(
            host=app["host"],
            port=int(app["port"]),
            user=master["username"],
            password=master["password"],
            dbname=master_database,
            autocommit=True,
            connect_timeout=10,
        ) as conn:
            step = "creating the role"
            role_exists = _exists(
                conn, "SELECT 1 FROM pg_roles WHERE rolname = %s", app["username"]
            )
            verb = "ALTER" if role_exists else "CREATE"
            conn.execute(sql.SQL(verb + " ROLE {} WITH LOGIN PASSWORD {}").format(role, password))
            # On RDS (PostgreSQL 16) the master must be a member to create a database it owns
            step = "granting the role to the master user"
            conn.execute(sql.SQL("GRANT {} TO CURRENT_USER").format(role))
            step = "creating the database"
            db_exists = _exists(conn, "SELECT 1 FROM pg_database WHERE datname = %s", app["dbname"])
            if not db_exists:
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(database, role))
            step = "limiting who can connect"
            conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(database))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
    except psycopg.Error as exc:
        detail = str(exc).splitlines()[0] if str(exc) else ""
        message = f"db-bootstrap failed while {step}: {type(exc).__name__}: {detail}"
        for secret in (str(master["password"]), str(app["password"])):
            message = message.replace(secret, "***")
        raise RuntimeError(message) from None
    return BootstrapResult(role_created=not role_exists, database_created=not db_exists)


def _exists(conn: psycopg.Connection, query: str, value: str) -> bool:
    return conn.execute(query, (value,)).fetchone() is not None

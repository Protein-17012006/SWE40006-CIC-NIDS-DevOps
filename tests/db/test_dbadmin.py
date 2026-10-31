import json
import uuid

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql

from app.config import database_url_from_secret, get_settings
from pipeline.cli import main
from pipeline.dbadmin import BootstrapResult, bootstrap


def _admin_conn(admin_url: str) -> psycopg.Connection:
    u = sa.make_url(admin_url)
    return psycopg.connect(
        host=u.host,
        port=u.port,
        user=u.username,
        password=u.password,
        dbname=u.database,
        autocommit=True,
    )


def _drop(admin_url: str, *roles: str) -> None:
    with _admin_conn(admin_url) as conn:
        for name in roles:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def _master(admin_url: str) -> str:
    u = sa.make_url(admin_url)
    return json.dumps({"username": u.username, "password": u.password})


def _app_secret(admin_url: str, name: str, password: str) -> str:
    u = sa.make_url(admin_url)
    return json.dumps(
        {"username": name, "password": password, "host": u.host, "port": u.port, "dbname": name}
    )


def _can_connect(secret_json: str) -> bool:
    engine = sa.create_engine(
        database_url_from_secret(secret_json), connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        return True
    except sa.exc.OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def name(admin_url):
    """A fresh role and database name; both are dropped after the test."""
    value = f"cicnids_t_{uuid.uuid4().hex[:8]}"
    yield value
    _drop(admin_url, value)


@pytest.mark.db
def test_bootstrap_is_idempotent(admin_url, name):
    secret = _app_secret(admin_url, name, "first-Pass1")
    assert bootstrap(_master(admin_url), secret) == BootstrapResult(True, True)
    assert bootstrap(_master(admin_url), secret) == BootstrapResult(False, False)
    engine = sa.create_engine(database_url_from_secret(secret))
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE t (x int)"))
    finally:
        engine.dispose()


@pytest.mark.db
def test_bootstrap_syncs_a_changed_password(admin_url, name):
    bootstrap(_master(admin_url), _app_secret(admin_url, name, "first-Pass1"))
    bootstrap(_master(admin_url), _app_secret(admin_url, name, "second-Pass2"))
    assert _can_connect(_app_secret(admin_url, name, "second-Pass2"))
    assert not _can_connect(_app_secret(admin_url, name, "first-Pass1"))


@pytest.mark.db
def test_bootstrap_with_punctuated_master_password(admin_url, name):
    master_name, password = f"{name}_m", "m@st:er/%pw!"
    with _admin_conn(admin_url) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN SUPERUSER PASSWORD {}").format(
                sql.Identifier(master_name), sql.Literal(password)
            )
        )
    try:
        master = json.dumps({"username": master_name, "password": password})
        assert bootstrap(master, _app_secret(admin_url, name, "x-Pass3")).database_created
    finally:
        _drop(admin_url, name, master_name)


@pytest.mark.db
def test_bootstrap_errors_hide_passwords(admin_url, name):
    wrong = json.dumps({"username": "postgres", "password": "not-the-password"})
    with pytest.raises(RuntimeError) as e:
        bootstrap(wrong, _app_secret(admin_url, name, "hidden-Pass4"))
    assert "not-the-password" not in str(e.value) and "hidden-Pass4" not in str(e.value)


@pytest.mark.db
def test_migrate_command_runs_upgrade(empty_db_url, settings_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", empty_db_url)
    get_settings.cache_clear()
    assert main(["migrate"]) == 0
    engine = sa.create_engine(empty_db_url)
    try:
        assert "datasets" in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

import json

import pytest

from pipeline.cli import main
from pipeline.dbadmin import bootstrap


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as e:
        main(["nope"])
    assert e.value.code == 2


def test_migrate_without_database_fails_cleanly(settings_env, capsys):
    assert main(["migrate"]) == 1
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (rec["event"], rec["status"]) == ("migrate", "failed")
    assert "DATABASE_URL" in rec["message"]


def test_bootstrap_rejects_unsafe_names():
    master = json.dumps({"username": "admin", "password": "x"})
    app = json.dumps(
        {
            "username": "x; DROP ROLE admin",
            "password": "p",
            "host": "h",
            "port": 5432,
            "dbname": "d",
        }
    )
    with pytest.raises(ValueError, match="username"):
        bootstrap(master, app)


def test_ingest_requires_a_key():
    with pytest.raises(SystemExit) as e:
        main(["ingest"])
    assert e.value.code == 2


def test_ingest_skips_a_key_that_is_not_a_raw_csv(capsys):
    from pipeline.ingest import ingest_file

    assert (
        ingest_file(
            "raw/readme.txt",
            engine=None,
            bucket=None,
            contracts=[],
            commit_sha="abc1234",
            workdir=None,
        )
        is None
    )
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (rec["event"], rec["key"]) == ("ingest_skipped", "raw/readme.txt")


def test_ingest_without_bucket_fails_cleanly(settings_env, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:1/d")
    assert main(["ingest", "--key", "raw/x.csv"]) == 1
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (rec["event"], rec["status"]) == ("ingest", "failed")
    assert "S3_BUCKET" in rec["message"]

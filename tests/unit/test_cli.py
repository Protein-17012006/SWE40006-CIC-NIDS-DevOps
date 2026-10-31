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

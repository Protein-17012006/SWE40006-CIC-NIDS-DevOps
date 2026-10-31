import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
needs_bash_and_jq = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None, reason="needs bash and jq"
)


def _overrides(*args: str) -> dict:
    result = subprocess.run(  # noqa: S603
        ["bash", "-c", 'source scripts/ci/lib.sh && container_overrides "$@"', "bash", *args],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@needs_bash_and_jq
def test_container_overrides_keeps_dash_arguments():
    assert _overrides("job", "python", "-m", "pipeline", "migrate") == {
        "containerOverrides": [{"name": "job", "command": ["python", "-m", "pipeline", "migrate"]}]
    }


@needs_bash_and_jq
def test_container_overrides_keeps_spaces_and_quotes():
    command = _overrides("job", "echo", 'a "b" c')["containerOverrides"][0]["command"]
    assert command == ["echo", 'a "b" c']

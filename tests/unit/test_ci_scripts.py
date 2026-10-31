import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# The bash on PATH, by full path: on Windows a bare "bash" starts WSL's from System32 instead
BASH = shutil.which("bash")
needs_bash_and_jq = pytest.mark.skipif(
    BASH is None or shutil.which("jq") is None, reason="needs bash and jq"
)


def _overrides(*args: str) -> dict:
    result = subprocess.run(  # noqa: S603
        [BASH, "-c", 'source scripts/ci/lib.sh && container_overrides "$@"', "bash", *args],
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


needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash")


@pytest.fixture
def fake_aws(tmp_path):
    """A PATH whose aws only records that it was called, so no test reaches AWS."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "aws"
    script.write_text('#!/usr/bin/env bash\necho "$*" >> "$FAKE_AWS_LOG"\nexit 99\n', newline="\n")
    script.chmod(0o755)
    return bin_dir, tmp_path / "aws-calls.log"


def _run(script: str, *args: str, fake) -> tuple[int, bool]:
    bin_dir, calls = fake
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_AWS_LOG": str(calls),
    }
    result = subprocess.run(  # noqa: S603
        [BASH, script, *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, calls.exists()


@needs_bash
@pytest.mark.parametrize("target", ["foo", "processed/x.csv", "raw", "raw/", ""])
def test_ingest_rejects_unknown_targets_before_aws(target, fake_aws):
    assert _run("scripts/ci/ingest.sh", "staging", target, fake=fake_aws) == (2, False)


@needs_bash
def test_ingest_rejects_unknown_environments_before_aws(fake_aws):
    assert _run("scripts/ci/ingest.sh", "prod", "status", fake=fake_aws) == (2, False)


@needs_bash
@pytest.mark.parametrize("target", ["status", "reconcile", "raw/cse-cic-ids2018/a b.csv"])
def test_ingest_passes_known_targets_on_to_aws(target, fake_aws):
    code, called = _run("scripts/ci/ingest.sh", "staging", target, fake=fake_aws)
    assert called and code != 2


@needs_bash
def test_run_task_reads_no_wait_before_the_environment(fake_aws):
    code, called = _run("scripts/ci/run_task.sh", "--no-wait", "staging", "job", fake=fake_aws)
    assert called and code != 2
    assert _run("scripts/ci/run_task.sh", "--no-wait", "staging", "web", fake=fake_aws)[0] == 2


@needs_bash
@pytest.mark.parametrize("env_name", ["test", "prod", ""])
def test_load_baseline_rejects_unknown_environments(env_name, fake_aws):
    assert _run("scripts/load_baseline.sh", env_name, fake=fake_aws) == (2, False)

import json
import os
import shutil
import subprocess
import sys
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


@pytest.fixture
def scripted_aws(tmp_path):
    """An aws that logs each call and answers the n-th describe-db-instances with line n of
    statuses.txt (the last line repeats), ending it with \r\n like the CLI on Windows."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "aws"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$FAKE_AWS_LOG"\n'
        'if [[ "$*" == *describe-db-instances* ]]; then\n'
        '  n=$(grep -c describe-db-instances "$FAKE_AWS_LOG")\n'
        '  line=$(sed -n "${n}p" "$FAKE_STATUSES")\n'
        '  [[ -n "$line" ]] || line=$(tail -n 1 "$FAKE_STATUSES")\n'
        "  printf '%s\r\n' \"$line\"\n"
        "fi\n",
        newline="\n",
    )
    script.chmod(0o755)
    return bin_dir, tmp_path


def _ensure(env_name, statuses, scripted, timeout_minutes=1) -> tuple[int, list[str]]:
    bin_dir, tmp = scripted
    (tmp / "statuses.txt").write_text("\n".join(statuses) + "\n", newline="\n")
    calls = tmp / "calls.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_AWS_LOG": str(calls),
        "FAKE_STATUSES": str(tmp / "statuses.txt"),
        "DB_POLL_SECONDS": "0",
        "DB_START_TIMEOUT_MINUTES": str(timeout_minutes),
    }
    result = subprocess.run(  # noqa: S603
        [BASH, "-c", 'source scripts/ci/lib.sh && ensure_database "$1"', "bash", env_name],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, calls.read_text().splitlines() if calls.exists() else []


def _kinds(calls):
    return ["start" if "start-db-instance" in c else "describe" for c in calls]


@needs_bash
def test_available_database_is_left_alone(scripted_aws):
    code, calls = _ensure("staging", ["available"], scripted_aws)
    assert code == 0 and _kinds(calls) == ["describe"] and "cicnids-nonprod" in calls[0]


@needs_bash
def test_stopped_database_is_started_once(scripted_aws):
    code, calls = _ensure("production", ["stopped", "starting", "available"], scripted_aws)
    assert code == 0 and _kinds(calls) == ["describe", "start", "describe", "describe"]
    assert "cicnids-prod" in calls[1]


@needs_bash
def test_stopping_database_is_started_after_it_stops(scripted_aws):
    code, calls = _ensure("test", ["stopping", "stopping", "stopped", "available"], scripted_aws)
    assert code == 0
    assert _kinds(calls) == ["describe", "describe", "describe", "start", "describe"]


@needs_bash
def test_database_start_gives_up_after_the_timeout(scripted_aws):
    code, calls = _ensure("development", ["starting"], scripted_aws, timeout_minutes=0)
    assert code == 1 and "start" not in _kinds(calls)


@needs_bash
def test_db_instance_rejects_unknown_environments():
    result = subprocess.run(  # noqa: S603
        [BASH, "-c", "source scripts/ci/lib.sh && db_instance prod"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


# The header line of Locust's _stats.csv
STATS_HEADER = (
    "Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,"
    "Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,"
    "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%"
)


@pytest.fixture
def fake_locust(tmp_path):
    """A locust that writes an Aggregated row with $FAKE_FAILURES failures to its --csv
    prefix, then waits to be stopped."""
    script = tmp_path / "locust"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'while (($#)); do [[ "$1" == --csv ]] && prefix=$2; shift; done\n'
        "printf '%s\\n,Aggregated,100,%s,1,1,1,1,1,1,0,1,1,1,1,1,150,1,1,1,1,1\\n' "
        f'"{STATS_HEADER}" "$FAKE_FAILURES" > "${{prefix}}_stats.csv"\n'
        "printf 'Method,Name,Error,Occurrences\\n' > \"${prefix}_failures.csv\"\n"
        "exec sleep 60\n",
        newline="\n",
    )
    script.chmod(0o755)
    return script


@needs_bash
@pytest.mark.parametrize(("failures", "code"), [(0, 0), (2, 1)])
def test_load_test_reports_the_verdict(fake_locust, tmp_path, failures, code):
    env = {
        **os.environ,
        "LOCUST": fake_locust.as_posix(),
        "PYTHON": Path(sys.executable).as_posix(),
        "FAKE_FAILURES": str(failures),
        "D": (tmp_path / "run").as_posix(),
    }
    result = subprocess.run(  # noqa: S603
        [
            BASH,
            "-c",
            'mkdir -p "$D" && source scripts/ci/lib.sh && source scripts/ci/load_test.sh'
            ' && load_test_start http://localhost:1 "$D" && sleep 2 && load_test_finish "$D" 0',
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == code and "Requests" in result.stdout

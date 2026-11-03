# M4 Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every release checks, watches and restarts itself: a deployment starts a stopped database, CloudWatch metrics, alarms and dashboards come with each environment's stack and email Hoàng, end-to-end tests gate test, Locust runs during staging and production deployments, a rollback drill is timed, and the demo is rehearsed.

**Architecture:** Five pull requests through the existing CI and CD, one part each. Bash helpers in `scripts/ci/` (database start, load test) are called by `deploy_env.sh`; CloudFormation in `infra/environment.yaml` carries the metric filters, alarms, dashboard and a test-only permission; a new one-off command `python -m pipeline e2e` runs inside the test environment's job task; Locust runs on the GitHub runner and a small Python verdict turns its statistics into pass or fail.

**Tech Stack:** M3's stack; CloudWatch metric filters, alarms and dashboards; Locust on the runner only; moto and AppTest for the new tests.

**Spec:** `docs/design/2026-11-03-operations-design.md`, on top of the build design (`docs/design/2026-10-31-build-design.md`) and the brief (`C:\Users\huyho\OneDrive\Desktop\project_brief\Project_Brief_CIC-NIDS_DevOps_v2.docx`, sections 3, 4.1 and 4.2). The M1 to M3 plans record what already exists.

## Global Constraints

- Every M1 to M3 global constraint still holds: venv `C:\Users\huyho\.venvs\cicnids`, `==` pins, JSON log lines without secrets or row data, `AWS_PROFILE=hoang` for AWS commands from the laptop (with `MSYS_NO_PATHCONV=1` in Git Bash before log group names such as `/cicnids/staging`), LF endings, commits ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Branches, in the order of design section 6.1, each cut from an up-to-date main after the previous one reached production: `feat/m4-database-start`, `feat/m4-monitoring`, `feat/m4-e2e`, `feat/m4-load-test`, `docs/m4-rollback-drill`, `feat/m4-upload-card`, `docs/m4-rehearsal`.
- The alert email address appears in no file, commit, pull request, issue or log line. It lives only in the repository secret `ALERT_EMAIL`. This plan does not contain it.
- Hoàng decides: the approvals of `production` and `platform`, executing the bootstrap change set, whether the builder may merge on green CI. Ask with the link, then wait.
- Names: namespace `CICNIDS`, dimension `Environment`; metrics `PageRenderTime`, `IngestionDuration`, `RejectedRows`, `FailedIngestions`; alarms `cicnids-<env>-5xx`, `cicnids-<env>-cpu`, `cicnids-<env>-memory`, `cicnids-<env>-unhealthy-targets`, `cicnids-<env>-failed-ingestion`; dashboard `cicnids-<env>`.
- Thresholds: CPU above 80%, memory above 85%. Every alarm has `TreatMissingData: notBreaching` and the alerts topic as both `AlarmActions` and `OKActions`.
- RDS: `cicnids-prod` for production, `cicnids-nonprod` for development, test and staging. A deployment waits up to 20 minutes for its instance. No role gets `rds:StopDBInstance`.
- End-to-end: the command runs only when `APP_ENV` is `test`; it waits up to 600 s for ingestion runs and should finish in at most 5 minutes.
- Locust: 20 users, spawn rate 5 per second, 1 to 5 s between a user's requests, staging and production only. Production's run lasts at least 300 s. Any failed request fails the deployment; a 95th percentile above 2,000 ms is a warning. Locust is pinned in `tests/load/requirements.txt` only: never in the image or the root requirements files.
- Lead time: merge to staging under 30 minutes, production within 15 minutes of approval. A miss is reported to Hoàng with the job timings, never hidden by relaxing a check.
- Shell: `set -euo pipefail`; shellcheck-clean; strip `\r` from AWS CLI text output before comparing it (the CLI on Windows ends lines with it).
- Checks: the test command `TEST_ADMIN_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres C:\Users\huyho\.venvs\cicnids\Scripts\python.exe -m pytest` with `docker compose up -d db` running (start Docker Desktop first); `python -m ruff check .` and `python -m ruff format --check .`; `C:\Users\huyho\.venvs\cicnids\Scripts\actionlint.exe`; `C:\Users\huyho\.venvs\cicnids\Scripts\cfn-lint.exe infra/*.yaml`; `docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable -x scripts/ci/*.sh scripts/load_baseline.sh`. CI keeps `--cov=pipeline --cov-fail-under=80`.
- Ledger: `.superpowers/sdd/2026-11-03-m4-operations/progress.md` (git-ignored), same format as M3's.

## Review Focus

1. **AWS CLI output that ends in `\r`.** From Git Bash on Windows, `describe-db-instances` prints `available\r`; the database start must still recognise every state. Pinned by Task 1: the scripted fake `aws` ends every answer with `\r\n`.
2. **An instance still `stopping`.** Hoàng stopped it minutes before a merge. The deployment waits, starts it exactly once after it reports `stopped`, and never calls start on a stopping instance. Pinned by Task 1 (`test_stopping_database_is_started_after_it_stops`).
3. **A load test that never really ran.** Locust missing on the runner, crashed, or the page shell listing no static files must fail the deployment, never pass with zero requests. Pinned by Task 8 (`test_no_requests_fails`, `test_missing_statistics_fail`, and the locustfile's failure when the shell lists no static files) and Task 9 (`test_load_test_reports_the_verdict`).
4. **Runs from before the end-to-end upload.** An older finished run of the same key, or an ingestion still running from the previous release, must not count as this run's result. Pinned by Task 5 (`test_wait_ignores_runs_from_before_the_upload`).
5. **Event names drifting from the metric filters.** Renaming `page_render`, `ingestion_run` or a command would silently empty the dashboard. Pinned by Task 3 (`test_metric_filters_read_events_the_code_logs`).

---

## Shipping a pull request

Every "Ship" task runs these steps; the task adds its title, requirement IDs and what to look at.

0. **AWS sign-in.** `aws sts get-caller-identity --profile hoang`. If it has expired, run `aws login --profile hoang` in the background and ask Hoàng to finish signing in in the browser.
1. **Local checks.** Every command in the Global Constraints' "Checks" line. Expected: all pass.
2. **Pull request.** `git push -u origin <branch>`, then `gh pr create` with the template filled in (design section, requirement IDs, definition-of-done ticks). If `gh pr edit` fails silently (the Projects classic deprecation met in M3), patch the body with `gh api -X PATCH repos/Protein-17012006/SWE40006-CIC-NIDS-DevOps/pulls/<n> -F body=@<file>`. Expected: `gh pr checks <n> --watch` shows lint, test, cfn-lint and image green.
3. **Merge** under the permission recorded in Task 2: `gh pr merge <n> --merge --delete-branch`.
4. **Watch CD** in the background (`gh run watch <id> --exit-status`) until staging finishes. For each environment, read the job log, then `aws logs filter-log-events --log-group-name /cicnids/<env> --start-time <deploy start in ms> --filter-pattern '{ $.level = "ERROR" }'`. Expected: deployed, smoke test passed, no ERROR lines except those the task expects.
5. **Production.** Ask Hoàng to approve `production` with the CD run's link, and wait. Expected: production deployed, the parity table shows the new tag everywhere, the same log check passes.
6. **Ledger.** Pull request, merge commit, run ids, merge-to-staging and approval-to-production minutes (`gh run view <id> --json jobs`), anything that differed.

---

### Task 1: Branch, docs and the database start

**Files:**
- Modify: `scripts/ci/lib.sh`, `scripts/ci/deploy_env.sh`, `scripts/ci/ingest.sh`, `infra/bootstrap.yaml`, `docs/runbook.md`, `.github/pull_request_template.md`
- Test: `tests/unit/test_ci_scripts.py`, `tests/unit/test_environment_template.py`
- Commit: `docs/design/2026-11-03-operations-design.md`, `docs/plans/2026-11-03-m4-operations.md`

**Interfaces:**
- Produces, in `lib.sh`:
  - `db_instance ENV`: prints `cicnids-prod` for production and `cicnids-nonprod` for development, test and staging; logs the usage and returns 2 for anything else.
  - `ensure_database ENV`: reads `DBInstanceStatus` of `db_instance ENV`. `available`: returns 0. `stopped`: logs, calls `aws rds start-db-instance` once, keeps polling. Any other state: logs and keeps polling. Polls every `DB_POLL_SECONDS` (default 20); returns 1 with a log line after `DB_START_TIMEOUT_MINUTES` (default 20).

- [ ] **Step 1: Branch, docs and ledger.** `git switch main && git pull && git switch -c feat/m4-database-start`. In `.github/pull_request_template.md`, replace the six definition-of-done lines with:

  ```markdown
  - [ ] It follows the design it implements (name the document and section)
  - [ ] For a page: usable at 1366 × 768, every chart goes through the guard and has a Hidden state, and AppTest passes on the labelled and the unlabelled fixture
  - [ ] No SQL outside `app/data/queries.py`, and no source column names outside `contracts/`
  - [ ] Logs hold no secrets or row data, and nothing here contains an email address
  - [ ] Scripts are shellcheck-clean and templates cfn-lint-clean
  - [ ] CI is green, and after merge the change runs in development
  ```

  Commit the template, the design and this plan: `Plan milestone 4: operations`. Start the ledger.

- [ ] **Step 2: Write the failing tests** in `tests/unit/test_ci_scripts.py`:

```python
@pytest.fixture
def scripted_aws(tmp_path):
    """An aws that logs each call and answers the n-th describe-db-instances with line n of
    statuses.txt (the last line repeats), ending it with \\r\\n like the CLI on Windows."""
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
        "  printf '%s\\r\\n' \"$line\"\n"
        "fi\n",
        newline="\n",
    )
    script.chmod(0o755)
    return bin_dir, tmp_path


def _ensure(env_name, statuses, scripted, timeout_minutes=1) -> tuple[int, list[str]]:
    bin_dir, tmp = scripted
    (tmp / "statuses.txt").write_text("\n".join(statuses) + "\n", newline="\n")
    calls = tmp / "calls.log"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "FAKE_AWS_LOG": str(calls), "FAKE_STATUSES": str(tmp / "statuses.txt"),
           "DB_POLL_SECONDS": "0", "DB_START_TIMEOUT_MINUTES": str(timeout_minutes)}
    result = subprocess.run(  # noqa: S603
        [BASH, "-c", 'source scripts/ci/lib.sh && ensure_database "$1"', "bash", env_name],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=60,
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
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 2
```

  And in `tests/unit/test_environment_template.py`:

```python
DEPLOY_ROLES = {
    "DeployRoleDevelopment": ("development", "cicnids-nonprod"),
    "DeployRoleTest": ("test", "cicnids-nonprod"),
    "DeployRoleStaging": ("staging", "cicnids-nonprod"),
    "DeployRoleProduction": ("production", "cicnids-prod"),
}


def _actions(statement: dict) -> list[str]:
    action = statement.get("Action", [])
    return [action] if isinstance(action, str) else list(action)


@pytest.mark.parametrize("role", sorted(DEPLOY_ROLES))
def test_deploy_role_may_start_only_its_own_database(role):
    env_name, instance = DEPLOY_ROLES[role]
    statements = policy(resources("bootstrap.yaml")[role], f"deploy-{env_name}")
    rds = [s for s in statements if any(a.startswith("rds:") for a in _actions(s))]
    assert len(rds) == 1
    assert sorted(_actions(rds[0])) == ["rds:DescribeDBInstances", "rds:StartDBInstance"]
    assert rds[0]["Resource"] == {
        "Fn::Sub": f"arn:${{AWS::Partition}}:rds:${{AWS::Region}}:${{AWS::AccountId}}:db:{instance}"
    }


def test_no_role_may_stop_a_database():
    text = (INFRA / "bootstrap.yaml").read_text(encoding="utf-8")
    assert "rds:Stop" not in text and "rds:*" not in text
```

- [ ] **Step 3: Run them to see them fail.** Run: the test command with `tests/unit/test_ci_scripts.py tests/unit/test_environment_template.py`. Expected: the five database tests fail (`ensure_database: command not found`, exit 127) and the four role tests fail (no `rds:` statement).

- [ ] **Step 4: Implement `db_instance` and `ensure_database` in `scripts/ci/lib.sh`.** A loop: read the status with `--query 'DBInstances[0].DBInstanceStatus' --output text | tr -d '\r'`, act on it as the Interfaces block says, check the deadline (`SECONDS`), sleep. Then call `ensure_database "$env_name"` in `deploy_env.sh` right after the tag check, as step "0. A database stopped by hand comes back first (5 to 10 minutes)", and in `ingest.sh` just before its `exec` line, after the argument checks (the existing tests require that a bad argument exits 2 before any `aws` call).

- [ ] **Step 5: Add the RDS statement** to each deploy role's policy in `infra/bootstrap.yaml`: `Action: [rds:DescribeDBInstances, rds:StartDBInstance]`, `Resource` the ARN of the role's instance as in the test.

- [ ] **Step 6: Run the tests and the linters.** The test command, ruff, shellcheck and cfn-lint. Expected: PASS, no findings.

- [ ] **Step 7: Runbook.** Rewrite "Stop and start environments by hand": stopping stays by hand (the `update-service --desired-count 0` and `stop-db-instance` commands for all four services and both instances); starting needs nothing by hand, because every deployment (CD and Rollback) and every Ingest run starts a stopped instance and a stopped service, and the first one after a stop takes 5 to 10 minutes longer. In "First-time setup" step 1, add that the deploy roles may start, never stop, their tier's RDS instance.

- [ ] **Step 8: Commit** — message `Start a stopped database before deploying or ingesting`.

### Task 2: Ship pull request 1 — the database start

Title "M4: start a stopped database before deploying"; design section 4.1; requirement IDs OPS-03, OPS-05, ING-01.

- [ ] **Step 1: Preview the bootstrap change** from the laptop: `aws cloudformation deploy --template-file infra/bootstrap.yaml --stack-name cicnids-bootstrap --capabilities CAPABILITY_NAMED_IAM --tags Project=cic-nids Environment=shared --region us-east-1 --no-execute-changeset`, then `aws cloudformation describe-change-set` on the change set it names. Expected: only the four `DeployRole*` resources, `Modify`, `Replacement` False.
- [ ] **Step 2: Execute it after Hoàng's go-ahead.** Ask, naming the change (each deploy role may start its tier's RDS instance). Then `aws cloudformation execute-change-set` and `aws cloudformation wait stack-update-complete --stack-name cicnids-bootstrap`. Expected: `UPDATE_COMPLETE`.
- [ ] **Step 3: Shipping steps 1 and 2.**
- [ ] **Step 4: Merge permission.** Ask Hoàng whether the builder may merge each M4 pull request once CI is green, as in M3. Record the answer in the ledger. Without it, ask before each merge.
- [ ] **Step 5: Merge with AWS still off.** `aws rds describe-db-instances --query 'DBInstances[].[DBInstanceIdentifier,DBInstanceStatus]' --output text` shows both `stopped`; then shipping steps 3 and 4. Expected: the development job logs `cicnids-nonprod is stopped; starting it`, then the usual deployment; test and staging find it available. The Infrastructure run that the `bootstrap.yaml` change starts deploys nothing new and waits for `platform`: ask Hoàng to approve or reject it, so it does not sit pending.
- [ ] **Step 6: Shipping steps 5 and 6.** Expected: the production job starts `cicnids-prod` and deploys. Ledger: how long each instance took to start.

### Task 3: Monitoring and the alarm email

**Files:**
- Modify: `infra/environment.yaml`, `infra/platform.yaml`, `.github/workflows/infra.yml`, `docs/runbook.md`
- Test: `tests/unit/test_environment_template.py`

**Interfaces:**
- Consumes: the log events of design section 3 (`page_render.duration_ms`; `ingestion_run.duration_s` and `rows_rejected`; command lines with `event` in `pipeline.cli.COMMANDS` and `status` `failed`); the platform exports `AlbArn` and `AlertTopicArn`.
- Produces, in `environment.yaml`: metric filters `PageRenderTimeFilter`, `IngestionDurationFilter`, `RejectedRowsFilter`, `FailedIngestionsFilter`; alarms `ServerErrorsAlarm`, `CpuAlarm`, `MemoryAlarm`, `UnhealthyTargetsAlarm`, `FailedIngestionAlarm`; `Dashboard`; output `DashboardName`.

Metric filters, all on `LogGroup`, `MetricNamespace: CICNIDS`, `Dimensions: [{Key: Environment, Value: $.env}]`:

| Resource | FilterPattern | MetricName | MetricValue | Unit |
| --- | --- | --- | --- | --- |
| PageRenderTimeFilter | `{ $.event = "page_render" }` | PageRenderTime | `$.duration_ms` | Milliseconds |
| IngestionDurationFilter | `{ $.event = "ingestion_run" }` | IngestionDuration | `$.duration_s` | Seconds |
| RejectedRowsFilter | `{ $.event = "ingestion_run" }` | RejectedRows | `$.rows_rejected` | Count |
| FailedIngestionsFilter | `{ ($.event = "ingest" \|\| $.event = "reconcile") && $.status = "failed" }` (the backslashes only escape this table: the pattern has a plain `\|\|`) | FailedIngestions | `1` | Count |

Alarms; `LB` is the load balancer's full name, `!Select [1, !Split ["loadbalancer/", <AlbArn import>]]`, and `TG` is `!GetAtt TargetGroup.TargetGroupFullName`:

| Resource | Name suffix | Metric | Dimensions | Statistic | Period | Periods / datapoints | Fires at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ServerErrorsAlarm | `5xx` | AWS/ApplicationELB HTTPCode_Target_5XX_Count | LoadBalancer LB, TargetGroup TG | Sum | 60 | 3 / 3 | ≥ 1 |
| CpuAlarm | `cpu` | AWS/ECS CPUUtilization | ClusterName, ServiceName | Average | 60 | 5 / 5 | > 80 |
| MemoryAlarm | `memory` | AWS/ECS MemoryUtilization | ClusterName, ServiceName | Average | 60 | 5 / 5 | > 85 |
| UnhealthyTargetsAlarm | `unhealthy-targets` | AWS/ApplicationELB UnHealthyHostCount | LoadBalancer LB, TargetGroup TG | Maximum | 60 | 3 / 3 | ≥ 1 |
| FailedIngestionAlarm | `failed-ingestion` | CICNIDS FailedIngestions | Environment | Sum | 60 | 1 / 1 | ≥ 1 |

The failed-ingestion alarm uses 1-minute periods, not the design's 5, so the forced failure's email lands well within the brief's 5 minutes; it recovers a minute later and sends the recovery email. Derive LB from the existing `AlbArn` export: a new platform export would not exist yet when CD deploys development, because the platform update waits for approval.

Dashboard widgets, in this order, each titled exactly so (`DashboardBody` is one `!Sub` string that is JSON once its `${...}` are filled):

| Title | Metrics |
| --- | --- |
| Requests | RequestCount (Sum) of TG |
| Latency | TargetResponseTime (p50, p95) of TG |
| Errors | HTTPCode_Target_5XX_Count and HTTPCode_Target_4XX_Count (Sum) of TG |
| CPU and memory | AWS/ECS CPUUtilization and MemoryUtilization (Average) of the service |
| Network in and out | ECS/ContainerInsights NetworkRxBytes and NetworkTxBytes (Average) of the service |
| Targets | HealthyHostCount and UnHealthyHostCount (Maximum) of TG |
| Page render time | CICNIDS PageRenderTime (p95, Maximum) |
| Ingestion | CICNIDS IngestionDuration (Maximum) and RejectedRows (Sum) |
| Failed ingestions | CICNIDS FailedIngestions (Sum) |
| Alarms | an alarm widget listing the five alarms |

Two departures from the design, for the ledger: the load balancer's own 5xx count exists only for the whole load balancer, which all four environments share, so Errors shows the targets' 5xx and 4xx instead; and every environment keeps the network widget, which has data only in production (Container Insights), so one template body serves all four.

- [ ] **Step 1: Read the baselines.** For each of the four services, `aws cloudwatch get-metric-statistics --namespace AWS/ECS --metric-name CPUUtilization` and `MemoryUtilization`, dimensions `ClusterName` and `ServiceName`, the last 14 days, `--period 3600 --statistics Average Maximum`. Record the highest hourly averages in the ledger. Expected: CPU below 65% and memory below 75%. Otherwise stop and show Hoàng the numbers before going on: an alarm that is always on is an anti-goal.

- [ ] **Step 2: Write the failing tests** in `tests/unit/test_environment_template.py`:

```python
ALARMS = {
    "ServerErrorsAlarm": "5xx",
    "CpuAlarm": "cpu",
    "MemoryAlarm": "memory",
    "UnhealthyTargetsAlarm": "unhealthy-targets",
    "FailedIngestionAlarm": "failed-ingestion",
}
TOPIC = {"Fn::ImportValue": {"Fn::Sub": "${PlatformStack}-AlertTopicArn"}}


@pytest.mark.parametrize("name", sorted(ALARMS))
def test_alarm_emails_and_ignores_stopped_environments(name):
    p = resources()[name]["Properties"]
    assert p["AlarmName"] == {"Fn::Sub": f"cicnids-${{EnvName}}-{ALARMS[name]}"}
    assert p["AlarmActions"] == [TOPIC] and p["OKActions"] == [TOPIC]
    assert p["TreatMissingData"] == "notBreaching"


def test_cpu_and_memory_thresholds_are_the_briefs():
    r = resources()
    assert r["CpuAlarm"]["Properties"]["Threshold"] == 80
    assert r["MemoryAlarm"]["Properties"]["Threshold"] == 85


def test_metric_filters_read_events_the_code_logs():
    from pipeline.cli import COMMANDS

    filters = [r["Properties"] for r in resources().values() if r["Type"] == "AWS::Logs::MetricFilter"]
    names = {f["MetricTransformations"][0]["MetricName"] for f in filters}
    assert names == {"PageRenderTime", "IngestionDuration", "RejectedRows", "FailedIngestions"}
    events = {e for f in filters for e in re.findall(r'\$\.event = "([a-z_-]+)"', f["FilterPattern"])}
    assert events <= {"page_render", "ingestion_run", *COMMANDS}
    assert '"page_render"' in (REPO / "app/telemetry.py").read_text(encoding="utf-8")
    assert '"ingestion_run"' in (REPO / "pipeline/ingest.py").read_text(encoding="utf-8")


def test_dashboard_shows_what_the_brief_lists():
    body = resources()["Dashboard"]["Properties"]["DashboardBody"]["Fn::Sub"]
    text = body[0] if isinstance(body, list) else body
    widgets = json.loads(re.sub(r"\$\{[^}]+\}", "x", text))["widgets"]
    assert [w["properties"]["title"] for w in widgets] == [
        "Requests", "Latency", "Errors", "CPU and memory", "Network in and out", "Targets",
        "Page render time", "Ingestion", "Failed ingestions", "Alarms",
    ]


def test_alert_email_stays_hidden():
    assert load(str(INFRA / "platform.yaml"))["Parameters"]["AlertEmail"]["NoEcho"] is True
    workflow = (REPO / ".github/workflows/infra.yml").read_text(encoding="utf-8")
    assert "secrets.ALERT_EMAIL" in workflow and "vars.ALERT_EMAIL" not in workflow
```

  (`REPO = INFRA.parent`; import `re` at the top.)

- [ ] **Step 3: Run them to see them fail.** Expected: KeyError on the missing resources, and the NoEcho and workflow assertions fail.
- [ ] **Step 4: Add the resources** to `infra/environment.yaml` with the values in the tables above, and the output `DashboardName`. In `platform.yaml`, `AlertEmail` gets `NoEcho: true`; in `infra.yml`, both `ALERT_EMAIL:` lines read `${{ secrets.ALERT_EMAIL }}`.
- [ ] **Step 5: Run the tests and the linters.** Expected: PASS; cfn-lint clean.
- [ ] **Step 6: Runbook.** A new section "Monitoring and alarms": the dashboard names and the console link `https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/cicnids-production`; the five alarms and what each means; that stopped environments raise none; that emails go to the address in the `ALERT_EMAIL` secret after its one-time confirmation. Under it, "Test the alarms": run the Ingest workflow with the environment and the target `raw/alarm-test.csv`; the run fails on the missing file by design, the `failed-ingestion` alarm emails within 5 minutes, and the recovery email follows. In "First-time setup" step 2, `ALERT_EMAIL` becomes an optional repository secret instead of a variable.
- [ ] **Step 7: Commit** — message `Add metric filters, alarms and a dashboard to every environment`.

### Task 4: Ship pull request 2 — monitoring and the alarm email

Title "M4: monitoring, alarms and the alert email"; design section 4.2; requirement IDs NFR-05, OPS-06.

- [ ] **Step 1: The secret.** `gh secret set ALERT_EMAIL --body <the address Hoàng gave on 3 November>`. Expected: `gh secret list` shows `ALERT_EMAIL`. The address goes nowhere else.
- [ ] **Step 2: Shipping steps 1 and 2.** Expected also: the Infrastructure preview's summary shows `cicnids-platform` adding `AlertSubscription` and nothing else, and no change to `cicnids-databases`.
- [ ] **Step 3: Merge (shipping step 3).** Two runs start: Infrastructure, waiting for `platform`, and CD.
- [ ] **Step 4: The subscription.** Ask Hoàng to approve `platform`. When the run is done, ask Hoàng to open the email "AWS Notification - Subscription Confirmation" and confirm. Expected: `aws sns list-subscriptions-by-topic --topic-arn <AlertTopicArn> --query 'Subscriptions[].SubscriptionArn' --output text` shows an ARN, not `PendingConfirmation`. Query only that field, so the address is never printed.
- [ ] **Step 5: Shipping step 4,** then for staging: `aws cloudwatch describe-alarms --alarm-name-prefix cicnids-staging- --query 'MetricAlarms[].[AlarmName,StateValue]' --output text` lists five alarms and none in `ALARM`; `aws cloudwatch get-dashboard --dashboard-name cicnids-staging` answers. Open each staging page once in a browser (Playwright with the installed Edge, as in M3), then within 5 minutes `get-metric-statistics` for `CICNIDS PageRenderTime` with `Environment=staging` returns datapoints.
- [ ] **Step 6: Forced failure in staging.** `gh workflow run ingest.yml -f environment=staging -f target=raw/alarm-test.csv`. Expected: the run fails on the missing file; `cicnids-staging-failed-ingestion` reaches `ALARM`; Hoàng confirms the email and says how many minutes it took (target: within 5); the recovery email follows. Ledger the times.
- [ ] **Step 7: Shipping steps 5 and 6.** Also: render each metric widget of `cicnids-production` with `aws cloudwatch get-metric-widget-image` into the scratchpad and read the images. Expected: data in every widget but Failed ingestions, and Ingestion if nothing was ingested. `aws cloudwatch describe-alarm-history --alarm-name-prefix cicnids- --history-item-type StateUpdate --start-date <merge time>` shows no transition to `ALARM` except the forced failure's: a routine deployment raises no alarm.

### Task 5: The end-to-end command

**Files:**
- Create: `pipeline/e2e.py`, `tests/db/test_e2e.py`
- Modify: `pipeline/cli.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `pipeline.load.TABLES`, `start_run`, `finish_run`, `RunRecord`; `Bucket.upload(path, key)`, `exists(key)`, `delete_prefix(prefix) -> int`; `parse_raw_key(key) -> RawFile | None` (`.dataset_id`, `.report_key`, `.draft_key`); `load_contracts()` (`Contract.name`, `.has_label`); `ingest_file(...)` (tests only, standing in for EventBridge); `app.components.filters.DATASET_KEY`; `app.components.layout.CARD_FAILED`.
- Produces, in `pipeline/e2e.py`:
  - `ROOT = Path(__file__).resolve().parents[1]`; `SAMPLES = ROOT / "tests" / "contracts"`; `VIEWS = ROOT / "app" / "views"`; `RESET_PREFIXES = ("raw/", "processed/", "quarantine/")`; `RUN_TIMEOUT_S = 600`.
  - `@dataclass(frozen=True) class Sample: path: Path; key: str; contract: str | None; missing: tuple[str, ...]`.
  - `samples(root: Path = SAMPLES) -> list[Sample]`: each `<root>/<contract>/*.csv` as `raw/<contract>/<file>` with that contract; each `<root>/broken/*.csv` as `raw/<file>` with `contract=None` and `missing` from `broken/expected.yaml`; sorted by key.
  - `db_now(engine) -> datetime` (`SELECT now()`, the database's clock).
  - `reset(engine, bucket) -> None`: one `TRUNCATE <TABLES> RESTART IDENTITY`, then `delete_prefix` for each of `RESET_PREFIXES`.
  - `upload(bucket, items: Sequence[Sample]) -> None`.
  - `@dataclass(frozen=True) class Finished: key: str; status: str; message: str; rows_loaded: int; dataset_id: str`.
  - `wait_for_runs(engine, keys, since, *, timeout_s=RUN_TIMEOUT_S, poll_s=10, sleep=time.sleep) -> dict[str, Finished]`: per key, the newest run with `started_at >= since` whose status is not `running`. Loop: query; return when every key has one; return what it has once `timeout_s` has passed (monotonic clock); else `sleep(poll_s)`.
  - `check(items, finished, contracts, bucket, engine) -> list[str]`: one message per broken expectation, each starting with the key: `"<key>: no finished run"` (and nothing else for that key); `"<key>: <status>, expected loaded"` or `"... expected quarantined"`, followed by the run's message (and no further checks for that key); then, for a loaded sample, `"<key>: no rows loaded"` and `"<key>: has_label is <x>, expected <y>"`; for a quarantined file, `"<key>: report missing"`, `"<key>: the report does not name <field>"` (its text read with `bucket.read_text(report_key)`) and `"<key>: draft contract missing"`.
  - `render_pages(dataset_ids, views: Path = VIEWS) -> list[str]`: for each dataset and each `views/*.py`, `AppTest.from_file(str(view), default_timeout=60)` with `session_state[DATASET_KEY] = dataset_id`, then `run()`; a message `"<view name> on <dataset>: <what>"` for an exception, any `st.error`, or a `CARD_FAILED` warning. Imports `streamlit.testing.v1` inside the function.
  - `run(engine, bucket, contracts, *, sleep=time.sleep, views: Path = VIEWS) -> list[str]`: `since = db_now()` before anything else, then reset, upload `samples()`, wait, check, render every dataset whose status is `loaded`; logs one `e2e_check` line per sample and per page (`check`, `ok`, `detail`) and an `e2e_summary` line (`checks`, `failed`, `duration_s`); returns every failure message.
- Produces, in `pipeline/cli.py`: command `e2e` ("reset the test environment, ingest every contract-test sample through S3, check the results and render every page"). It raises `RuntimeError("e2e resets its database and bucket, so it runs only in the test environment")` unless `APP_ENV` is `test`, and `RuntimeError(f"{n} end-to-end checks failed; the first: {failures[0]}")` when any fail.

- [ ] **Step 1: Write the failing tests** in `tests/db/test_e2e.py` (every test `@pytest.mark.db`; `engine` and `bucket` are the conftest fixtures):

```python
KEY = "raw/cse-cic-ids2018/wednesday-14-02-2018.csv"


def ingest_on_upload(engine, bucket, workdir):
    """A sleep for wait_for_runs that does EventBridge's job: it ingests each raw/ key that
    has no run yet, as the job task would."""
    def sleep(_seconds):
        listed = bucket.client.list_objects_v2(Bucket=bucket.name, Prefix="raw/")
        keys = sorted(o["Key"] for o in listed.get("Contents", []))
        with engine.connect() as conn:
            seen = set(conn.execute(sa.text("SELECT file_key FROM ingestion_runs")).scalars())
        for key in keys:
            if key not in seen:
                with contextlib.suppress(Exception):  # a failed run is recorded, like the job's
                    ingest_file(key, engine=engine, bucket=bucket, contracts=load_contracts(),
                                commit_sha="e2e0000", workdir=workdir)
    return sleep


def test_samples_cover_every_contract_folder_and_broken_file():
    items = {s.key: s for s in samples()}
    assert items[KEY].contract == "cse-cic-ids2018" and items[KEY].missing == ()
    broken = items["raw/missing-dst-port.csv"]
    assert broken.contract is None and broken.missing == ("dst_port",)


def test_reset_empties_the_tables_and_the_bucket(engine, bucket, tmp_path):
    upload(bucket, samples())
    ingest_on_upload(engine, bucket, tmp_path)(0)
    reset(engine, bucket)
    with engine.connect() as conn:
        assert all(conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one() == 0 for t in TABLES)  # noqa: S608
    assert "Contents" not in bucket.client.list_objects_v2(Bucket=bucket.name)


def test_run_passes_when_ingestion_behaves(engine, bucket, tmp_path, settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("S3_BUCKET", bucket.name)
    clear_caches()
    assert run(engine, bucket, load_contracts(), sleep=ingest_on_upload(engine, bucket, tmp_path)) == []


def test_wait_ignores_runs_from_before_the_upload(engine):
    old = start_run(engine, "cse-cic-ids2018", KEY, "old0000")
    finish_run(engine, old, RunRecord(status="loaded", message="old", rows_loaded=5))
    since = db_now(engine)
    assert wait_for_runs(engine, [KEY], since, timeout_s=0, sleep=lambda s: None) == {}


def test_check_names_each_broken_expectation(engine, bucket):
    good = next(s for s in samples() if s.key == KEY)
    broken = next(s for s in samples() if s.key == "raw/missing-dst-port.csv")
    finished = {
        good.key: Finished(good.key, "quarantined", "no contract", 0, "cse-cic-ids2018"),
        broken.key: Finished(broken.key, "loaded", "ok", 10, "missing-dst-port"),
    }
    messages = check([good, broken], finished, load_contracts(), bucket, engine)
    assert any(m.startswith(f"{good.key}: quarantined, expected loaded") for m in messages)
    assert any(m.startswith(f"{broken.key}: loaded, expected quarantined") for m in messages)
    assert check([good], {}, load_contracts(), bucket, engine) == [f"{good.key}: no finished run"]


def test_render_pages_reports_a_page_that_raises(tmp_path, settings_env):
    (tmp_path / "boom.py").write_text("raise RuntimeError('boom')\n")
    assert render_pages(["cse-cic-ids2018"], views=tmp_path)[0].startswith("boom on cse-cic-ids2018:")
```

  And in `tests/unit/test_cli.py`:

```python
def test_e2e_refuses_outside_test(settings_env, monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "staging")
    assert main(["e2e"]) == 1
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (rec["event"], rec["status"]) == ("e2e", "failed") and "only in the test" in rec["message"]
```

- [ ] **Step 2: Run them to see them fail.** Expected: `ModuleNotFoundError: No module named 'pipeline.e2e'`, and `invalid choice: 'e2e'` (exit 2) for the CLI test.
- [ ] **Step 3: Implement `pipeline/e2e.py` and the `e2e` command** with the Interfaces block's names, values and messages. `wait_for_runs` reads `SELECT DISTINCT ON (file_key) file_key, status, message, rows_loaded, dataset_id FROM ingestion_runs WHERE file_key = ANY(:keys) AND started_at >= :since ORDER BY file_key, run_id DESC` and drops `running` rows. `check` reads `has_label` from `datasets`.
- [ ] **Step 4: Run the tests.** The test command with `tests/db/test_e2e.py tests/unit/test_cli.py`, then the whole suite with coverage. Expected: PASS, and coverage of `pipeline/` still at least 80%.
- [ ] **Step 5: Commit** — message `Add the end-to-end command for the test environment`.

### Task 6: The end-to-end test in deployments to test

**Files:**
- Modify: `infra/environment.yaml`, `scripts/ci/deploy_env.sh`, `Dockerfile`, `.dockerignore`, `docs/runbook.md`
- Test: `tests/unit/test_environment_template.py`

**Interfaces:**
- Consumes: `python -m pipeline e2e` (Task 5): exit 0 when every check passed, 1 otherwise.
- Produces: the condition `IsTest`; in test only, the task role may delete any object in its bucket.

- [ ] **Step 1: Write the failing test.** Replace `test_task_role_may_delete_only_processed_objects` with:

```python
def test_only_test_may_delete_outside_processed():
    statements = policy(resources()["TaskRole"], "own-bucket")
    plain = [s for s in statements if "Fn::If" not in s and "s3:DeleteObject" in _actions(s)]
    assert plain == [
        {"Effect": "Allow", "Action": "s3:DeleteObject", "Resource": {"Fn::Sub": "${Bucket.Arn}/processed/*"}}
    ]
    assert [s for s in statements if "Fn::If" in s] == [
        {"Fn::If": ["IsTest",
                    {"Effect": "Allow", "Action": "s3:DeleteObject", "Resource": {"Fn::Sub": "${Bucket.Arn}/*"}},
                    {"Ref": "AWS::NoValue"}]}
    ]
    conditions = load(str(INFRA / "environment.yaml"))["Conditions"]
    assert conditions["IsTest"] == {"Fn::Equals": [{"Ref": "EnvName"}, "test"]}
```

- [ ] **Step 2: Run it to see it fail.** Expected: the `Fn::If` list is empty and `Conditions` is missing.
- [ ] **Step 3: Template.** Add `Conditions: IsTest: !Equals [!Ref EnvName, test]` and, at the end of the `own-bucket` statements, the `!If` statement of the test, with a comment that only test's end-to-end run resets its bucket.
- [ ] **Step 4: Deploy script.** Replace step 6 of `deploy_env.sh`:

```bash
# 6. Rollbacks skip both commands below: an older image may not have them.
#    In test, the end-to-end test resets test's data, ingests every contract-test sample through
#    S3 and EventBridge, and renders every page; a failure stops the release before staging.
#    Elsewhere, re-ingest the files the new contracts read differently (ING-09), without waiting.
if [[ "$skip_migrations" == true ]]; then
  log "rollback: not starting reconcile or the end-to-end test"
elif [[ "$env_name" == test ]]; then
  TASK_TIMEOUT_MINUTES=15 bash scripts/ci/run_task.sh test job python -m pipeline e2e
else
  bash scripts/ci/run_task.sh --no-wait "$env_name" job python -m pipeline reconcile
fi
```

- [ ] **Step 5: Image.** In `Dockerfile`, `COPY tests/contracts/ tests/contracts/` after `COPY contracts/`. In `.dockerignore`, after `tests`, add `!tests/contracts` and `tests/contracts/**/*.py`. Verify: `docker build -t cicnids:e2e .`, then `docker run --rm cicnids:e2e python -c "from pipeline.e2e import samples; print(len(samples()))"` prints 4, and `docker run --rm cicnids:e2e find tests -name '*.py'` prints nothing.
- [ ] **Step 6: Run the tests and the linters.** Expected: PASS; cfn-lint and shellcheck clean.
- [ ] **Step 7: Runbook.** In "Environments", say that every deployment to test resets test's database and bucket and runs the end-to-end test, whose `e2e_check` lines appear in the test job's log; in "How a release flows" step 3, that test runs the end-to-end test where the others start reconcile.
- [ ] **Step 8: Commit** — message `Run the end-to-end test after every deployment to test`.

### Task 7: Ship pull request 3 — end-to-end tests in test

Title "M4: end-to-end tests in test"; design section 4.3; requirement IDs OPS-07 and the brief's quality gate.

- [ ] **Step 1: Shipping steps 1 to 4.** Expected in the test job's log: one `e2e_check` line per sample and per page, all `"ok": true`, and an `e2e_summary` with `"failed": 0`; the job passes. Ledger the end-to-end task's duration (at most 5 minutes) and the run's merge-to-staging minutes (under 30). If either is over, show Hoàng the job timings before going on.
- [ ] **Step 2: Look at test.** `http://cicnids-1239707461.us-east-1.elb.amazonaws.com:8081/pipeline` lists `cse-cic-ids2018` loaded and the broken samples quarantined.
- [ ] **Step 3: Shipping steps 5 and 6.**

### Task 8: The load test and its verdict

**Files:**
- Create: `tests/load/locustfile.py`, `tests/load/shell.py`, `tests/load/requirements.txt`, `scripts/load_verdict.py`, `tests/unit/test_load_test.py`

**Interfaces:**
- Produces:
  - `tests.load.shell.static_paths(html: str) -> list[str]`: every `./static/...` path the page shell names in a `src=` or `href=` attribute, as an absolute path (`/static/...`), without duplicates, in page order. Standard library only.
  - `scripts/load_verdict.py`: `@dataclass class Verdict: requests: int; failures: int; server_errors: int; p95_ms: float | None; ok: bool; notes: list[str]`; `verdict(stats_csv: Path, failures_csv: Path, *, p95_limit_ms: float = 2000) -> Verdict`; `summary(v: Verdict) -> str` (a heading `### Load test` and a one-row Markdown table with the columns `Requests | Failures | 5xx | p95 (ms)`, then the notes); `main(argv: list[str] | None = None) -> int` (`python -m scripts.load_verdict STATS FAILURES`: prints the summary, prints `::warning::<note>` for each note when the verdict is ok and `::error::<note>` otherwise, returns 0 when ok and 1 otherwise). Standard library only.
  - Rules: read the `Aggregated` row of Locust's `_stats.csv` (`Request Count`, `Failure Count`, `95%`). `ok` requires the file, at least one request and no failure. `server_errors` sums `Occurrences` over `_failures.csv` rows whose `Error` contains a three-digit code from 500 to 599. Notes, exactly: `"Locust wrote no statistics"`, `"Locust sent no requests"`, `"3 requests failed, 2 of them with a 5xx"`, `"p95 2,500 ms is above 2,000 ms"` (values formatted with thousands separators).
  - `tests/load/locustfile.py`: `class Viewer(HttpUser)` with `wait_time = between(1, 5)`. `on_start` gets `/` with `catch_response=True`, keeps `static_paths(response.text)`, and marks the response failed with `"the page shell lists no static files"` when that list is empty. Tasks: `/` (weight 3, name `/`), `/_stcore/health` (weight 2), a random kept asset (weight 1, name `/static/*`).
  - `tests/load/requirements.txt`: `locust==<the newest release at least two weeks old>` (`pip index versions locust`).

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_load_test.py`:

```python
from scripts.load_verdict import main, verdict
from tests.load.shell import static_paths

STATS = ("Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,"
         "Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,"
         "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%")


def stats(tmp_path, requests, failures, p95):
    path = tmp_path / "locust_stats.csv"
    path.write_text(f"{STATS}\nGET,/,{requests},{failures},40,50,10,900,500,4,0,40,45,50,55,70,{p95},300,400,800,900,900\n"
                    f",Aggregated,{requests},{failures},40,50,10,900,500,4,0,40,45,50,55,70,{p95},300,400,800,900,900\n")
    return path


def failures_csv(tmp_path, rows):
    path = tmp_path / "locust_failures.csv"
    path.write_text("Method,Name,Error,Occurrences\n" + "".join(f'{m},{n},"{e}",{c}\n' for m, n, e, c in rows))
    return path


def test_clean_run_passes(tmp_path):
    v = verdict(stats(tmp_path, 1200, 0, 180), failures_csv(tmp_path, []))
    assert (v.ok, v.requests, v.failures, v.server_errors, v.p95_ms, v.notes) == (True, 1200, 0, 0, 180, [])


def test_any_failure_fails_and_5xx_are_counted(tmp_path):
    rows = [("GET", "/", "HTTPError('503 Server Error: Service Unavailable for url: /')", 2),
            ("GET", "/_stcore/health", "ConnectionResetError(104, 'Connection reset by peer')", 1)]
    v = verdict(stats(tmp_path, 1200, 3, 200), failures_csv(tmp_path, rows))
    assert not v.ok and (v.failures, v.server_errors) == (3, 2)
    assert v.notes == ["3 requests failed, 2 of them with a 5xx"]


def test_slow_run_only_warns(tmp_path, capsys):
    s, f = stats(tmp_path, 1200, 0, 2500), failures_csv(tmp_path, [])
    assert verdict(s, f).notes == ["p95 2,500 ms is above 2,000 ms"]
    assert main([str(s), str(f)]) == 0
    assert "::warning::p95 2,500 ms is above 2,000 ms" in capsys.readouterr().out


def test_no_requests_fails(tmp_path):
    v = verdict(stats(tmp_path, 0, 0, 0), failures_csv(tmp_path, []))
    assert not v.ok and v.notes == ["Locust sent no requests"]


def test_missing_statistics_fail(tmp_path):
    v = verdict(tmp_path / "none_stats.csv", tmp_path / "none_failures.csv")
    assert not v.ok and v.notes == ["Locust wrote no statistics"]


def test_static_paths_reads_scripts_preloads_and_styles():
    shell = ('<link rel="shortcut icon" href="./favicon.png" />'
             '<script type="module" crossorigin src="./static/js/index.Dlja0TUX.js"></script>'
             '<link rel="modulepreload" crossorigin href="./static/js/react-dom.CbzydqoA.js">'
             '<link rel="modulepreload" crossorigin href="./static/js/react-dom.CbzydqoA.js">')
    assert static_paths(shell) == ["/static/js/index.Dlja0TUX.js", "/static/js/react-dom.CbzydqoA.js"]
    assert static_paths("<html></html>") == []
```

- [ ] **Step 2: Run them to see them fail.** Expected: `ModuleNotFoundError: No module named 'scripts.load_verdict'`.
- [ ] **Step 3: Implement** `tests/load/shell.py` (one regular expression over `src`/`href` attributes) and `scripts/load_verdict.py` (the `csv` module), then the locustfile and its requirements file.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Try it locally.** `docker compose up -d --build`; in a scratch venv (`py -3.12 -m venv <scratchpad>/locustenv`, then install `tests/load/requirements.txt`), from the repo root: `locust -f tests/load/locustfile.py --headless -u 5 -r 5 -t 30s --host http://localhost:8501 --csv <scratchpad>/locust`, then `python -m scripts.load_verdict <scratchpad>/locust_stats.csv <scratchpad>/locust_failures.csv`. Expected: exit 0, requests on `/`, `/_stcore/health` and `/static/*`. Again with `docker compose stop app`. Expected: exit 1 with connection failures. Then `docker compose start app`.
- [ ] **Step 6: Commit** — message `Add the Locust load test and the verdict that judges it`.

### Task 9: The load test in deployments

**Files:**
- Create: `scripts/ci/load_test.sh`
- Modify: `scripts/ci/deploy_env.sh`, `.github/workflows/deploy.yml`, `docs/runbook.md`
- Test: `tests/unit/test_ci_scripts.py`

**Interfaces:**
- Consumes: `python -m scripts.load_verdict STATS FAILURES` (Task 8).
- Produces, in `load_test.sh` (sourced, functions only):
  - `load_test_start URL DIR`: starts `${LOCUST:-locust} -f tests/load/locustfile.py --headless --users 20 --spawn-rate 5 --run-time 30m --host URL --csv DIR/locust --only-summary` in the background with its output in `DIR/locust.log`; writes `DIR/pid` and `DIR/started` (epoch seconds).
  - `load_test_finish DIR MIN_SECONDS`: sleeps until `MIN_SECONDS` have passed since the start, stops Locust with SIGTERM and waits for it, runs `${PYTHON:-python} -m scripts.load_verdict DIR/locust_stats.csv DIR/locust_failures.csv`, prints its output and also appends it to `$GITHUB_STEP_SUMMARY` when that is set, and returns the verdict's exit code.
  - `load_test_abort DIR`: kills a Locust that is still running, for `trap ... EXIT`.

- [ ] **Step 1: Write the failing test** in `tests/unit/test_ci_scripts.py`:

```python
@pytest.fixture
def fake_locust(tmp_path):
    """A locust that writes an Aggregated row with $FAKE_FAILURES failures to its --csv
    prefix, then waits to be stopped."""
    script = tmp_path / "locust"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'while (($#)); do [[ "$1" == --csv ]] && prefix=$2; shift; done\n'
        f'printf "%s\\n,Aggregated,100,%s,1,1,1,1,1,1,0,1,1,1,1,1,150,1,1,1,1,1\\n" "{STATS_HEADER}" '
        '"$FAKE_FAILURES" > "${prefix}_stats.csv"\n'
        "printf 'Method,Name,Error,Occurrences\\n' > \"${prefix}_failures.csv\"\n"
        "exec sleep 60\n",
        newline="\n",
    )
    script.chmod(0o755)
    return script


@needs_bash
@pytest.mark.parametrize(("failures", "code"), [(0, 0), (2, 1)])
def test_load_test_reports_the_verdict(fake_locust, tmp_path, failures, code):
    env = {**os.environ, "LOCUST": str(fake_locust), "PYTHON": sys.executable,
           "FAKE_FAILURES": str(failures), "D": str(tmp_path / "run")}
    result = subprocess.run(  # noqa: S603
        [BASH, "-c", 'mkdir -p "$D" && source scripts/ci/lib.sh && source scripts/ci/load_test.sh'
                     ' && load_test_start http://localhost:1 "$D" && sleep 2 && load_test_finish "$D" 0'],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == code and "Requests" in result.stdout
```

  (`STATS_HEADER` is the header line of Locust's `_stats.csv`, as in Task 8's tests; the summary table's first column header is `Requests`.)

- [ ] **Step 2: Run it to see it fail.** Expected: `scripts/ci/load_test.sh: No such file or directory`.
- [ ] **Step 3: Implement `load_test.sh`**, then wire it into `deploy_env.sh`: source it next to `lib.sh`. For staging and production, set `load_dir=${LOAD_TEST_DIR:-$(mktemp -d)}`, `trap 'load_test_abort "$load_dir"' EXIT`, and call `load_test_start "http://$(stack_output cicnids-platform AlbDnsName):$(stack_output "$stack" ListenerPort)" "$load_dir"` just before step 4 (the app update). After the smoke test, call `load_test_finish "$load_dir" 300` in production and `load_test_finish "$load_dir" 0` in staging. A non-zero verdict fails the script.
- [ ] **Step 4: Workflow.** In `deploy.yml`, for staging and production only (`if: inputs.environment == 'staging' || inputs.environment == 'production'`): `actions/setup-python@v7` with Python 3.12 and pip caching on `tests/load/requirements.txt`, then `pip install -r tests/load/requirements.txt`, both before "Deploy the image"; `LOAD_TEST_DIR: ${{ runner.temp }}/locust` in that step's `env`; and after it, `if: always()` with the same environment condition, `actions/upload-artifact` at its newest major (`gh api repos/actions/upload-artifact/releases/latest --jq .tag_name`) with `name: locust-${{ inputs.environment }}-${{ inputs.image_tag }}`, `path: ${{ runner.temp }}/locust` and `if-no-files-found: ignore`. The install is its own step rather than overlapping the stack update, as design section 5 suggested: with pip's cache it takes about 15 seconds, and overlapping it would mean a virtual environment inside `deploy_env.sh` (Ubuntu 24.04's system Python refuses `pip install`). Ledger this departure.
- [ ] **Step 5: Run the tests and the linters.** Expected: PASS; shellcheck and actionlint clean.
- [ ] **Step 6: Runbook.** A section "Load test": what runs during staging and production deployments (and their rollbacks), where the summary and the statistics artifact are, what fails a deployment and what only warns; and how to explore by hand with Locust's web UI: `locust -f tests/load/locustfile.py --host http://cicnids-1239707461.us-east-1.elb.amazonaws.com:8080`.
- [ ] **Step 7: Commit** — message `Run the load test during staging and production deployments`.

### Task 10: Ship pull request 4 — the load test

Title "M4: load test during deployments"; design section 4.4; requirement IDs NFR-02, and the brief's performance and availability metrics.

- [ ] **Step 1: Shipping steps 1 to 4.** Expected in the staging job: the Locust summary in the job summary with requests above 0, failures 0 and 5xx 0, and the artifact `locust-staging-<tag>`. Ledger the 95th percentile and the merge-to-staging minutes (under 30).
- [ ] **Step 2: Shipping steps 5 and 6.** Expected in the production job: Locust ran at least 300 s with 20 users, failures 0, and the production job finished within 15 minutes of approval. The production dashboard's Requests widget, rendered with `get-metric-widget-image`, shows the load during the deployment, and `describe-alarm-history` shows no `ALARM` during either deployment: the load raised no CPU or memory alarm (the brief's "CPU below 80%").

### Task 11: Rollback drill

Design section 4.5; OPS-05 and the brief's time to restore.

- [ ] **Step 1: Back.** Make sure no CD run waits at the production gate (runbook, "Roll back"). Then `gh workflow run rollback.yml -f environment=production -f image_tag=<the tag PR 3 shipped>` and ask Hoàng to approve. Expected: the smoke test passes within 10 minutes of the approval (the approval time from `gh api repos/Protein-17012006/SWE40006-CIC-NIDS-DevOps/actions/runs/<id>/approvals`, the end from the job log's "production runs <tag> and is healthy"), and the Locust summary shows failures 0.
- [ ] **Step 2: Forward.** The same with the tag PR 4 shipped. Expected: the same limits; the parity table shows that tag everywhere.
- [ ] **Step 3: Runbook.** In "Roll back", replace the 31 October drill sentence with both timings and the Locust results of this drill. Branch `docs/m4-rollback-drill`, pull request, green CI, merge; CD skips docs.
- [ ] **Step 4: Ledger** both run ids and timings.

### Task 12: Upload card (ING-10, Could)

Before starting, ask Hoàng whether there is time for the upload card. If not, skip Tasks 12 and 13 and ledger that.

**Files:**
- Modify: `pipeline/storage.py`, `app/data/storage.py`, `app/views/pipeline_page.py`, `.streamlit/config.toml`, `docs/runbook.md`
- Test: `tests/unit/test_storage.py`, `tests/unit/test_app_storage.py`, `tests/app/test_pipeline_page.py`

**Interfaces:**
- Produces:
  - `Bucket.put_bytes(key: str, data: bytes, content_type: str) -> None` in `pipeline/storage.py`.
  - `app.data.storage.upload_key(name: str) -> str | None`: `raw/<name>` when `name` contains no `/` or `\` and `parse_raw_key("raw/" + name)` accepts it; otherwise None.
  - `app.data.storage.upload_raw(name: str, data: bytes) -> str | None`: puts `data` at `upload_key(name)` with content type `text/csv` and returns the key. Returns None without a bucket, and returns None after logging `upload_failed` (ERROR, fields `key` and `message`) when S3 refuses. Raises `ValueError` when `upload_key(name)` is None.
  - In `pipeline_page.py`, `upload_card() -> None`, drawn last, after "Quarantined files", with this copy exactly:
    - title `Upload a CSV`; caption `The file goes to raw/ as its own dataset, and ingestion starts within a minute or two.`
    - `NO_BUCKET = "Uploads need an environment's bucket, so this card works only in AWS."` (no form)
    - `UPLOADS_OFF = "Uploads are switched off here: this environment has no upload password."` (no form)
    - inside `st.form("upload")`: `st.text_input("Upload password", type="password", key="upload-password")`, `st.file_uploader("CSV file", type=["csv"], key="upload-file")`, `st.form_submit_button("Upload", key="upload-submit", icon=":material/upload:")`
    - `CHOOSE_FILE = "Choose a CSV file first."` (warning); `WRONG_PASSWORD = "Wrong password. Nothing was uploaded."` (error; logs `upload_refused`, WARNING, field `file`); `BAD_NAME = "The file name must be a plain name ending in .csv."` (error)
    - `UPLOADED = "Uploaded {name}. Ingestion starts within a minute or two; the run then appears under Recent ingestion runs."` (success; logs `upload_done`, fields `key` and `bytes`); `UPLOAD_FAILED = "The upload failed. The logs have the error."` (error)
  - The password check is `hmac.compare_digest` on UTF-8 bytes against `settings.upload_password`.

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_app_storage.py`:

```python
@pytest.mark.parametrize(("name", "key"), [
    ("simulated-real-traffic-02.csv", "raw/simulated-real-traffic-02.csv"),
    ("Capture 1.CSV", "raw/Capture 1.CSV"),
    ("a/b.csv", None), ("..\\b.csv", None), ("notes.txt", None), (".csv", None),
])
def test_upload_key(name, key):
    assert upload_key(name) == key


def test_upload_raw_puts_the_file_in_raw(bucket, settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("S3_BUCKET", bucket.name)
    clear_caches()
    assert upload_raw("x.csv", b"a,b\n1,2\n") == "raw/x.csv"
    assert bucket.read_text("raw/x.csv") == "a,b\n1,2\n"


def test_upload_raw_without_a_bucket(settings_env):
    assert upload_raw("x.csv", b"a\n") is None
```

  In `tests/unit/test_storage.py`, `test_put_bytes_round_trips(bucket)`: `put_bytes("raw/x.csv", b"a\n", "text/csv")`, then `read_text` returns `"a\n"`. In `tests/unit/test_theme.py`, assert `config["server"]["maxUploadSize"] == 100`. In `tests/app/test_pipeline_page.py` (every test `@pytest.mark.db`):

```python
def _upload(at, password, file):
    at.text_input(key="upload-password").input(password)
    at.file_uploader(key="upload-file").set_value(file)
    return at.button(key="upload-submit").click().run()


def test_upload_card_needs_a_bucket(run_app):
    at = run_app("views/pipeline_page.py")
    assert NO_BUCKET in [c.value for c in at.caption] and not at.file_uploader


def test_upload_card_is_off_without_a_password(run_app, bucket, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", bucket.name)
    at = run_app("views/pipeline_page.py")
    assert UPLOADS_OFF in [c.value for c in at.caption] and not at.file_uploader


def test_upload_card_refuses_a_wrong_password(run_app, bucket, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", bucket.name)
    monkeypatch.setenv("UPLOAD_PASSWORD", "right")
    at = _upload(run_app("views/pipeline_page.py"), "wrong", ("x.csv", b"a\n1\n", "text/csv"))
    assert at.error[0].value == WRONG_PASSWORD and not bucket.exists("raw/x.csv")


def test_upload_card_uploads_with_the_password(run_app, bucket, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", bucket.name)
    monkeypatch.setenv("UPLOAD_PASSWORD", "right")
    at = _upload(run_app("views/pipeline_page.py"), "right", ("x.csv", b"a\n1\n", "text/csv"))
    assert at.success[0].value == UPLOADED.format(name="x.csv")
    assert bucket.read_text("raw/x.csv") == "a\n1\n"
```

- [ ] **Step 2: Run them to see them fail.** Expected: ImportError on `upload_key`, `upload_raw` and the page's copy constants.
- [ ] **Step 3: Implement** `put_bytes`, `upload_key`, `upload_raw` and `upload_card()` as the Interfaces block says; in `.streamlit/config.toml`, add `[server]` with `maxUploadSize = 100`.
- [ ] **Step 4: Run the tests.** Expected: PASS, with the existing Pipeline page tests unchanged.
- [ ] **Step 5: Runbook.** In "Load data", a paragraph on uploading through the Pipeline page, and how to read the password: `aws secretsmanager get-secret-value --secret-id <ARN of cicnids/<env>/upload-password-...> --query SecretString --output text` (find the ARN with `aws secretsmanager list-secrets --filters Key=name,Values=cicnids/<env>/upload-password`). In "Demo: merge the simulated contract", the upload goes through the card.
- [ ] **Step 6: Commit** — message `Add the upload card to the Pipeline page`.

### Task 13: Ship pull request 5 — the upload card

Title "M4: upload card"; design section 4.6; requirement ID ING-10.

- [ ] **Step 1: Shipping steps 1 to 4.**
- [ ] **Step 2: Upload in development.** With Playwright and the installed Edge (as in M3: a scratch venv with `playwright==1.55.0`, `channel="msedge"`), open `:8082/pipeline`, enter development's upload password (read as in the runbook, passed to the script through an environment variable, never printed), choose `tests/contracts/broken/missing-dst-port.csv`, press Upload. Expected: the success message; within 3 minutes `aws logs filter-log-events --log-group-name /cicnids/development --filter-pattern '{ $.event = "ingestion_run" && $.file_key = "raw/missing-dst-port.csv" }'` shows a quarantined run. A wrong password shows `WRONG_PASSWORD` and starts nothing.
- [ ] **Step 3: Shipping steps 5 and 6.**

### Task 14: Final review, rehearsal and close-out

- [ ] **Step 1: Final review** of every M4 commit (`git log ed3fb4c..main`), as the chosen execution method says. Fix each Critical or Important finding test-first; each fix ships as its own small pull request through Shipping. Ledger the rest as deferred minors.
- [ ] **Step 2: Rehearsal** with Hoàng (design section 4.7), timing each step into the ledger. It needs Hoàng's approvals for two production rollbacks and one production Ingest run.
  1. Production shows the baseline; open each page once first.
  2. Generate the simulated file into the scratchpad (runbook, "Simulated real traffic"), then upload it to production and to development (the card, or `aws s3 cp` if Tasks 12 and 13 were skipped). Expected: quarantined in both; the draft contract downloads from the Pipeline page.
  3. On a branch `rehearsal/simulated-contract`, apply the runbook's demo change, open the pull request, watch CI's contract tests pass, close it unmerged.
  4. `gh workflow run cd.yml --ref rehearsal/simulated-contract` (development only). Expected: reconcile loads the file in development, and its pages hide the label charts. Then Rollback with `development` and main's tag.
  5. A pull request with a deliberately failing test. Expected: CI red, merge blocked, production unchanged. Close it and delete the branch.
  6. Roll production back to the previous tag and forward again (Task 11's commands), and during the first of these run the Ingest workflow on production with `raw/alarm-test.csv`. Expected: the production dashboard shows the load and the `failed-ingestion` alarm together (render it with `get-metric-widget-image`), and Hoàng receives the alarm email within 5 minutes.
- [ ] **Step 3: Write it up.** Rewrite the runbook's "Demo" section as a script: what to click and show at each step, the timings measured, and where it can stall (first page loads, a stopped RDS adding 5 to 10 minutes, approvals, the production gate's lock on rollbacks). Set the README status line to `Milestone 4 (operations) is live: every release is checked end to end in test and under load in staging and production, and CloudWatch alarms email the team.` Branch `docs/m4-rehearsal`, pull request, green CI, merge.
- [ ] **Step 4: Close out.** Ask Hoàng whether any alarm email arrived on a night when the environments were stopped (expected: none), and ledger the answer. Update the project memory: M4 done, the rehearsal's results, what is next (the demo). Report the cost so far from Cost Explorer. Ask Hoàng whether to switch AWS off. Then follow superpowers:finishing-a-development-branch.

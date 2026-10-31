# M1 Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An app shell that shows its environment, version and database status, packaged in one Docker image, checked by CI on every pull request and deployed by GitHub Actions through CloudFormation to development, test and staging automatically and to production after approval, with smoke tests and a rollback workflow.

**Architecture:** Streamlit shell (`app/`) over a small data layer; a `pipeline` CLI in the same image runs migrations and the per-environment database bootstrap as one-off ECS tasks. CloudFormation is split into bootstrap (OIDC, IAM), platform (network, ALB, ECR, clusters, SNS, budget), databases (two RDS instances) and one stack per environment. Workflow logic lives in bash scripts under `scripts/ci/`, so the YAML stays thin.

**Tech Stack:** Python 3.12, Streamlit, pandas, SQLAlchemy 2, psycopg 3, Alembic, pytest, ruff, Docker, GitHub Actions, AWS CloudFormation, ECS Fargate, RDS PostgreSQL 16.

**Spec:** `docs/design/2026-10-31-build-design.md`, built on the Design and Requirements Report and the requirements document. M1 covers design section 10, step 1.

## Global Constraints

- Python 3.12 (`py -3.12`); Streamlit 1.40 or later; PostgreSQL 16; every direct dependency pinned with `==` in `requirements.txt` / `requirements-dev.txt`, at the latest release available when Task 1 runs.
- Local virtual environment at `C:\Users\huyho\.venvs\cicnids`, outside OneDrive. Run tools as `C:\Users\huyho\.venvs\cicnids\Scripts\python.exe -m <tool>`.
- Start command, exactly: `streamlit run app/main.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true`.
- `/_stcore/health` answers 200 within 60 s of start, even when the database is down; a database error never stops the server.
- Environment variables only, read in `app/config.py`: `APP_ENV` (local, development, test, staging, production), `APP_VERSION`, `AWS_REGION`, `S3_BUCKET`, `DATABASE_URL` or `DB_SECRET`, `UPLOAD_PASSWORD`; the admin task adds `DB_MASTER_SECRET`.
- Logs: one JSON object per line on stdout with `ts`, `level`, `env`, `version`, `event`; never passwords, secrets, `DATABASE_URL` or row data.
- No secrets in the repository; `.env` is git-ignored; `.env.example` lists every variable with dummy values.
- Names: stacks `cicnids-bootstrap`, `cicnids-platform`, `cicnids-databases`, `cicnids-<env>`; ECR repository `cic-nids`; clusters `cicnids-prod`, `cicnids-nonprod`; ports development 8082, test 8081, staging 8080, production 80; log group `/cicnids/<env>`; secrets `cicnids/<env>/db`, `cicnids/<env>/upload-password`; database and role `cicnids_<env>`; image tag = first 7 characters of the commit hash.
- Region us-east-1. Every stack is deployed with tags `Project=cic-nids` and `Environment=<env or shared>`. Never modify resources without `Project=cic-nids`.
- Dashboard queries are read-only; schema changes only through Alembic.
- LF line endings (`.gitattributes`), commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. The database is unreachable when the app starts (RDS still creating, wrong password, migrations not yet run): the health check stays 200, the Pipeline page shows "Unreachable" or "runs table not available", nothing crashes. Pinned by Task 5 (`test_ping_unreachable_database_fails_fast`), Task 6 (`test_tiles_with_unreachable_database`) and Task 7 (container health without a database).
2. A deployment re-runs for the same commit: the image push skips an existing immutable tag, `db-bootstrap` and `migrate` are no-ops. Pinned by Task 3 (`test_upgrade_twice_is_a_no_op`), Task 4 (`test_bootstrap_is_idempotent`) and Task 14 (`push_image.sh` skips an existing tag), checked live in Task 15 step 10.
3. Passwords with URL-special characters: the RDS-managed master password contains punctuation. Pinned by Task 1 (`test_database_url_built_from_secret_with_quoted_password`) and Task 4 (`test_bootstrap_with_punctuated_master_password`).
4. An environment stopped by hand (desired count 0) receives a deployment: it comes back to one task and the smoke test passes. Checked live in Task 15 step 11.
5. Secrets in logs or error messages. Pinned by Task 2 (`test_log_event_drops_sensitive_fields`), Task 4 (`test_bootstrap_errors_hide_passwords`) and Task 5 (`test_ping_unreachable_database_fails_fast` asserts no password in the error).

---

### Task 1: Project scaffold and settings

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.env.example`, `.streamlit/config.toml`, `app/__init__.py`, `app/config.py`, `tests/conftest.py`, `tests/unit/test_config.py`

**Interfaces:**
- Produces: `app.config.APP_ENVS: tuple[str, ...]`; frozen dataclass `Settings(app_env: str, app_version: str, aws_region: str, s3_bucket: str | None, database_url: str | None, upload_password: str | None, started_at: datetime)` with property `is_production: bool`; `load_settings(environ: Mapping[str, str] | None = None) -> Settings`; `get_settings() -> Settings` (cached with `functools.lru_cache(maxsize=1)`, so `get_settings.cache_clear()` exists); `database_url_from_secret(secret_json: str) -> str`. Fixture `settings_env(monkeypatch)` in `tests/conftest.py`: sets `APP_ENV=test`, `APP_VERSION=abc1234`, removes `DATABASE_URL`, `DB_SECRET`, `S3_BUCKET`, clears `get_settings` before and after.

- [ ] **Step 1: Create the virtual environment and pin dependencies**

Run: `py -3.12 -m venv C:\Users\huyho\.venvs\cicnids`, then look up the latest release of each package with `python -m pip index versions <name>`.
`requirements.txt`: `streamlit`, `pandas`, `sqlalchemy`, `psycopg[binary]`, `alembic`.
`requirements-dev.txt`: `pytest`, `pytest-cov`, `ruff`, `cfn-lint`, `actionlint-py`.
Install both files, then `python -m pip install -e .`.
Expected: `python -c "import streamlit, sqlalchemy, psycopg, alembic"` exits 0.

- [ ] **Step 2: Write `pyproject.toml`, `.env.example` and `.streamlit/config.toml`**

`pyproject.toml`: project `cicnids` 0.1.0, `requires-python = ">=3.12,<3.13"`, setuptools packages `app*`, `pipeline*`; ruff `line-length = 100`, `target-version = "py312"`, lint `select = ["E", "F", "W", "I", "B", "UP", "S"]`, tests ignore `S101`; pytest `pythonpath = ["."]`, `testpaths = ["tests"]`, marker `db: needs PostgreSQL via TEST_ADMIN_DATABASE_URL`.
`.env.example`: `APP_ENV=local`, `APP_VERSION=local`, `AWS_REGION=us-east-1`, `S3_BUCKET=`, `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/cicnids`, `UPLOAD_PASSWORD=change-me`, `TEST_ADMIN_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres`.
`.streamlit/config.toml`: the `[theme]` block from report section 5.1 verbatim (`primaryColor = "#2E3A59"`, `backgroundColor = "#FFFFFF"`, `secondaryBackgroundColor = "#F0F2F6"`, `textColor = "#31333F"`, `font = "sans serif"`) and `[browser] gatherUsageStats = false`.

- [ ] **Step 3: Write the failing tests**

```python
# tests/unit/test_config.py
def test_defaults_when_environment_is_empty():
    s = load_settings({})
    assert (s.app_env, s.app_version, s.aws_region) == ("local", "unknown", "us-east-1")
    assert s.s3_bucket is None and s.database_url is None and s.upload_password is None
    assert s.started_at.tzinfo is timezone.utc
    assert s.is_production is False

def test_reads_every_variable():
    s = load_settings({"APP_ENV": "production", "APP_VERSION": "3f2a9c1", "S3_BUCKET": "b",
                       "DATABASE_URL": "postgresql+psycopg://a:b@h:5432/d", "UPLOAD_PASSWORD": "pw"})
    assert (s.app_env, s.app_version, s.s3_bucket, s.upload_password) == ("production", "3f2a9c1", "b", "pw")
    assert s.database_url == "postgresql+psycopg://a:b@h:5432/d" and s.is_production

def test_rejects_unknown_app_env():
    with pytest.raises(ValueError, match="APP_ENV must be one of"):
        load_settings({"APP_ENV": "prod"})

def test_empty_s3_bucket_is_none():
    assert load_settings({"S3_BUCKET": ""}).s3_bucket is None

def test_database_url_built_from_secret_with_quoted_password():
    secret = json.dumps({"username": "cicnids_staging", "password": "p@ss/w:rd%", "host": "db.example",
                         "port": 5432, "dbname": "cicnids_staging"})
    assert database_url_from_secret(secret) == (
        "postgresql+psycopg://cicnids_staging:p%40ss%2Fw%3Ard%25@db.example:5432/cicnids_staging")

def test_db_secret_used_only_without_database_url():
    secret = json.dumps({"username": "u", "password": "p", "host": "h", "port": 5432, "dbname": "d"})
    assert load_settings({"DB_SECRET": secret}).database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert load_settings({"DB_SECRET": secret, "DATABASE_URL": "x"}).database_url == "x"

def test_secret_missing_key_is_named():
    with pytest.raises(ValueError, match="host"):
        database_url_from_secret(json.dumps({"username": "u", "password": "p", "port": 5432, "dbname": "d"}))
```

- [ ] **Step 4: Run the tests to see them fail**

Run: `python -m pytest tests/unit/test_config.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 5: Implement `app/config.py`**

`started_at` is `datetime.now(timezone.utc)` at load time; quote username and password with `urllib.parse.quote(value, safe="")`.

- [ ] **Step 6: Run the tests and the linters**

Run: `python -m pytest tests/unit/test_config.py; python -m ruff check .; python -m ruff format --check .`
Expected: 7 passed, no lint findings.

- [ ] **Step 7: Commit** — `git add` the files above; message `Add project scaffold and settings`.

### Task 2: Telemetry

**Files:**
- Create: `app/telemetry.py`, `tests/unit/test_telemetry.py`

**Interfaces:**
- Consumes: `get_settings()`.
- Produces: `SENSITIVE_KEYS = frozenset({"password", "database_url", "db_secret", "db_master_secret", "upload_password"})`; `log_event(event: str, *, level: str = "INFO", **fields: object) -> dict[str, object]` (prints the record as one JSON line, returns it; drops fields whose lower-cased name is in `SENSITIVE_KEYS`; falls back to `env`/`version` `"unknown"` if settings fail to load); context manager `page_render(page: str)` logging `{"event": "page_render", "page": page, "duration_ms": int}` at exit, with `level="ERROR"` and re-raise when the body raises.

- [ ] **Step 1: Write the failing tests**

```python
def test_log_event_prints_one_json_line(capsys, settings_env):
    log_event("ingestion_run", status="loaded", rows_read=10)
    lines = capsys.readouterr().out.strip().splitlines()
    rec = json.loads(lines[0])
    assert len(lines) == 1 and rec["event"] == "ingestion_run" and rec["level"] == "INFO"
    assert (rec["env"], rec["version"], rec["status"], rec["rows_read"]) == ("test", "abc1234", "loaded", 10)
    assert rec["ts"].endswith("Z")

def test_log_event_drops_sensitive_fields(capsys, settings_env):
    log_event("debug", password="x", database_url="postgresql://u:p@h/d", DB_SECRET="{}", page="overview")
    rec = json.loads(capsys.readouterr().out)
    assert {"password", "database_url", "DB_SECRET"}.isdisjoint(rec) and rec["page"] == "overview"

def test_page_render_logs_duration(capsys, settings_env):
    with page_render("pipeline"):
        pass
    rec = json.loads(capsys.readouterr().out)
    assert (rec["event"], rec["page"]) == ("page_render", "pipeline")
    assert isinstance(rec["duration_ms"], int) and rec["duration_ms"] >= 0

def test_page_render_logs_error_and_reraises(capsys, settings_env):
    with pytest.raises(RuntimeError):
        with page_render("overview"):
            raise RuntimeError("boom")
    assert json.loads(capsys.readouterr().out)["level"] == "ERROR"
```

- [ ] **Step 2: Run to see them fail** — `python -m pytest tests/unit/test_telemetry.py`; expected `ModuleNotFoundError`.
- [ ] **Step 3: Implement `app/telemetry.py`** — `ts` in UTC as `%Y-%m-%dT%H:%M:%S.mmmZ`; `json.dumps(record, default=str)`; `print(..., flush=True)`; timing with `time.perf_counter()`.
- [ ] **Step 4: Run the tests** — expected 4 passed; ruff clean.
- [ ] **Step 5: Commit** — `Add JSON logging and page render timing`.

### Task 3: Database schema and test databases

**Files:**
- Create: `docker-compose.yml` (service `db` only), `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_initial_schema.py`, `pipeline/__init__.py`, `pipeline/migrate.py`, `tests/db/test_migrations.py`
- Modify: `tests/conftest.py` (database fixtures)

**Interfaces:**
- Consumes: `get_settings()`.
- Produces: `pipeline.migrate.REPO_ROOT: Path`; `alembic_config(database_url: str) -> alembic.config.Config` (passes the URL through `config.attributes["database_url"]`, never through the ini, because ConfigParser would interpolate `%` in quoted passwords); `upgrade(database_url: str, revision: str = "head") -> None`; `downgrade(database_url: str, revision: str) -> None`. `migrations/env.py` uses `config.attributes["database_url"]`, else `get_settings().database_url`. Fixtures: `admin_url` (session; skips the test when `TEST_ADMIN_DATABASE_URL` is unset), `empty_db_url` (creates database `cicnids_t_<8 hex>` through `admin_url`, yields its URL, drops it `WITH (FORCE)` afterwards), `migrated_db_url` (`empty_db_url` after `upgrade`).
- Tables (revision `0001_initial_schema`), all column names exactly:
  - `datasets`: `dataset_id` text PK, `display_name` text not null, `contract_name` text, `contract_version` int, `status` text not null check in (`loaded`, `quarantined`), `has_label` bool not null default false, `fields` text[] not null default `{}`, `extra_fields` text[] not null default `{}`, `row_count` bigint not null default 0, `first_ts` timestamp, `last_ts` timestamp, `loaded_at` timestamptz.
  - `ingestion_runs`: `run_id` bigint identity PK, `dataset_id` text not null (indexed with `started_at`, no foreign key), `file_key` text not null, `contract_name` text, `contract_version` int, `commit_sha` text not null, `started_at` timestamptz not null default now(), `ended_at` timestamptz, `rows_read`, `rows_loaded`, `rows_rejected` bigint not null default 0, `source_columns`, `new_columns` text[] not null default `{}`, `status` text not null check in (`running`, `loaded`, `quarantined`, `failed`), `report_key`, `draft_contract_key`, `message` text.
  - `quality_steps`: `run_id` FK to `ingestion_runs` on delete cascade, `step` text, `rows_affected` bigint not null; PK (`run_id`, `step`).
  - `quality_columns`: `run_id` FK cascade, `column_name` text, `nulls` bigint not null default 0, `infinite` bigint not null default 0, `action` text not null; PK (`run_id`, `column_name`).
  - `agg_hourly`: `dataset_id` text not null, `file_key` text not null, `hour` timestamp, `label` text, `attack_category` text, `flows` bigint not null; indexes (`dataset_id`, `hour`) and (`dataset_id`, `file_key`).
  - `agg_ports`: `dataset_id`, `file_key` text not null, `day` date, `attack_category` text, `protocol` int not null, `dst_port` int not null, `flows` bigint not null; indexes (`dataset_id`, `day`) and (`dataset_id`, `file_key`).
  - `flow_sample`: `sample_id` bigint identity PK, `dataset_id`, `file_key` text not null, `ts` timestamp, `label`, `attack_category` text, `dst_port` int not null, `protocol` int not null, `flow_duration_us` double not null, `fwd_packets`, `bwd_packets` bigint not null, `fwd_bytes`, `bwd_bytes` double not null, `flow_bytes_per_s`, `flow_packets_per_s` double, `src_ip`, `dst_ip` text, `extras` jsonb not null default `{}`; indexes (`dataset_id`, `attack_category`) and (`dataset_id`, `file_key`).
- `docker-compose.yml` service `db`: `postgres:16`, user and password `postgres`, database `cicnids`, port 5432, healthcheck `pg_isready -U postgres -d cicnids`, named volume `pgdata`.

- [ ] **Step 1: Start Docker Desktop and the database** — `docker compose up -d db`; expected `docker compose ps` shows `db` healthy.
- [ ] **Step 2: Write the failing tests**

```python
EXPECTED = {
    "datasets": {"dataset_id", "display_name", "contract_name", "contract_version", "status", "has_label",
                 "fields", "extra_fields", "row_count", "first_ts", "last_ts", "loaded_at"},
    "ingestion_runs": {"run_id", "dataset_id", "file_key", "contract_name", "contract_version", "commit_sha",
                       "started_at", "ended_at", "rows_read", "rows_loaded", "rows_rejected", "source_columns",
                       "new_columns", "status", "report_key", "draft_contract_key", "message"},
    "quality_steps": {"run_id", "step", "rows_affected"},
    "quality_columns": {"run_id", "column_name", "nulls", "infinite", "action"},
    "agg_hourly": {"dataset_id", "file_key", "hour", "label", "attack_category", "flows"},
    "agg_ports": {"dataset_id", "file_key", "day", "attack_category", "protocol", "dst_port", "flows"},
    "flow_sample": {"sample_id", "dataset_id", "file_key", "ts", "label", "attack_category", "dst_port",
                    "protocol", "flow_duration_us", "fwd_packets", "bwd_packets", "fwd_bytes", "bwd_bytes",
                    "flow_bytes_per_s", "flow_packets_per_s", "src_ip", "dst_ip", "extras"},
}

@pytest.mark.db
def test_upgrade_creates_the_seven_tables(migrated_db_url):
    insp = sa.inspect(sa.create_engine(migrated_db_url))
    assert set(insp.get_table_names()) - {"alembic_version"} == set(EXPECTED)
    for table, cols in EXPECTED.items():
        assert {c["name"] for c in insp.get_columns(table)} == cols

@pytest.mark.db
def test_run_status_is_constrained(migrated_db_url):
    with sa.create_engine(migrated_db_url).begin() as c, pytest.raises(sa.exc.IntegrityError):
        c.execute(sa.text("INSERT INTO ingestion_runs (dataset_id, file_key, commit_sha, status) "
                          "VALUES ('d', 'raw/f.csv', 'abc1234', 'done')"))

@pytest.mark.db
def test_upgrade_twice_is_a_no_op(migrated_db_url):
    upgrade(migrated_db_url)

@pytest.mark.db
def test_downgrade_removes_every_table(migrated_db_url):
    downgrade(migrated_db_url, "base")
    assert set(sa.inspect(sa.create_engine(migrated_db_url)).get_table_names()) <= {"alembic_version"}
```

- [ ] **Step 3: Run to see them fail** — with `TEST_ADMIN_DATABASE_URL` set from `.env.example`: `python -m pytest tests/db/test_migrations.py`; expected FAIL on import of `pipeline.migrate`.
- [ ] **Step 4: Implement** `pipeline/migrate.py`, `alembic.ini` (`script_location = migrations`, no URL), `migrations/env.py`, the template and revision `0001_initial_schema` (with a full `downgrade`).
- [ ] **Step 5: Run the tests** — expected 4 passed; also `python -m pytest` with `TEST_ADMIN_DATABASE_URL` unset shows them skipped, not failed.
- [ ] **Step 6: Commit** — `Add the database schema as the first Alembic migration`.

### Task 4: Pipeline CLI: migrate and db-bootstrap

**Files:**
- Create: `pipeline/__main__.py`, `pipeline/cli.py`, `pipeline/dbadmin.py`, `tests/unit/test_cli.py`, `tests/db/test_dbadmin.py`

**Interfaces:**
- Consumes: `pipeline.migrate.upgrade`, `get_settings()`, `log_event()`.
- Produces: `python -m pipeline migrate` and `python -m pipeline db-bootstrap`; `pipeline.cli.main(argv: list[str] | None = None) -> int` (argparse subcommands; returns 0 or 1; logs one event named after the command with `status` `ok` or `failed` and a `message`); `pipeline.dbadmin.IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")`; frozen dataclass `BootstrapResult(role_created: bool, database_created: bool)`; `bootstrap(master_secret_json: str, app_secret_json: str, *, master_database: str = "postgres") -> BootstrapResult`. `db-bootstrap` reads `DB_MASTER_SECRET` and `DB_SECRET` from the environment.
- `bootstrap` connects with psycopg keyword arguments (never a URL) to `master_database` on the app secret's host and port, autocommit, `connect_timeout=10`; validates `username` and `dbname` with `IDENTIFIER_RE`; then: create the role `LOGIN PASSWORD` or `ALTER ROLE ... PASSWORD`; `GRANT <role> TO CURRENT_USER` (RDS on PostgreSQL 16 needs it to create a database owned by the role); `CREATE DATABASE <db> OWNER <role>` when missing; `REVOKE CONNECT ON DATABASE <db> FROM PUBLIC`; `GRANT CONNECT ON DATABASE <db> TO <role>`. Identifiers through `psycopg.sql.Identifier`, the password through `psycopg.sql.Literal`. Exceptions are re-raised as `RuntimeError` with a message that names the step and never the password.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cli.py
def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as e:
        main(["nope"])
    assert e.value.code == 2

def test_migrate_without_database_fails_cleanly(settings_env, capsys):
    assert main(["migrate"]) == 1
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (rec["event"], rec["status"]) == ("migrate", "failed") and "DATABASE_URL" in rec["message"]

def test_bootstrap_rejects_unsafe_names():
    master = json.dumps({"username": "admin", "password": "x"})
    app = json.dumps({"username": "x; DROP ROLE admin", "password": "p", "host": "h", "port": 5432, "dbname": "d"})
    with pytest.raises(ValueError, match="username"):
        bootstrap(master, app)

# tests/db/test_dbadmin.py (each test drops the role and database it made, in a finally block)
@pytest.mark.db
def test_bootstrap_is_idempotent(admin_url):
    assert bootstrap(MASTER, app_secret("first-Pass1")) == BootstrapResult(True, True)
    assert bootstrap(MASTER, app_secret("first-Pass1")) == BootstrapResult(False, False)
    with sa.create_engine(database_url_from_secret(app_secret("first-Pass1"))).begin() as c:
        c.execute(sa.text("CREATE TABLE t (x int)"))

@pytest.mark.db
def test_bootstrap_syncs_a_changed_password(admin_url):
    bootstrap(MASTER, app_secret("first-Pass1"))
    bootstrap(MASTER, app_secret("second-Pass2"))
    assert ping_with(app_secret("second-Pass2")) and not ping_with(app_secret("first-Pass1"))

@pytest.mark.db
def test_bootstrap_with_punctuated_master_password(admin_url):
    # creates a temporary superuser whose password is 'm@st:er/%pw!' and uses it as MASTER
    assert bootstrap(punctuated_master, app_secret("x-Pass3")).database_created

@pytest.mark.db
def test_bootstrap_errors_hide_passwords(admin_url):
    wrong = json.dumps({"username": "postgres", "password": "not-the-password"})
    with pytest.raises(RuntimeError) as e:
        bootstrap(wrong, app_secret("hidden-Pass4"))
    assert "not-the-password" not in str(e.value) and "hidden-Pass4" not in str(e.value)

@pytest.mark.db
def test_migrate_command_runs_upgrade(empty_db_url, settings_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", empty_db_url)
    get_settings.cache_clear()
    assert main(["migrate"]) == 0
    assert "datasets" in sa.inspect(sa.create_engine(empty_db_url)).get_table_names()
```

Helpers in the test module: `MASTER` from `admin_url`'s user and password; `app_secret(password)` with `username`/`dbname` `cicnids_t_<hex>`, host and port from `admin_url`; `ping_with(secret_json) -> bool`.

- [ ] **Step 2: Run to see them fail** — `python -m pytest tests/unit/test_cli.py tests/db/test_dbadmin.py`; expected import errors.
- [ ] **Step 3: Implement** `pipeline/cli.py`, `pipeline/__main__.py` (`raise SystemExit(main())`) and `pipeline/dbadmin.py`.
- [ ] **Step 4: Run the tests** — expected 8 passed; `python -m pytest --cov=pipeline --cov-report=term-missing` shows `pipeline/` at 80% or more.
- [ ] **Step 5: Commit** — `Add the pipeline CLI with migrate and db-bootstrap`.

### Task 5: Data access for the shell

**Files:**
- Create: `app/data/__init__.py`, `app/data/db.py`, `app/data/queries.py`, `tests/unit/test_db.py`, `tests/db/test_queries.py`

**Interfaces:**
- Consumes: `get_settings()`.
- Produces: frozen dataclass `PingResult(ok: bool, latency_ms: int | None, server_version: str | None, error: str | None)`; `make_engine(database_url: str) -> sa.Engine` (`pool_pre_ping=True`, `pool_size=5`, `connect_args={"connect_timeout": 3}`); `get_engine() -> sa.Engine | None` (`@st.cache_resource`; `None` without a database URL); `ping(engine: sa.Engine | None) -> PingResult` (`SELECT 1`, then `SHOW server_version` keeping the first token; `error` is `"DATABASE_URL is not set"` for `None`, otherwise the exception class name and the first line of its message); `queries.last_ingestion_run() -> pd.DataFrame` with columns `run_id`, `started_at`, at most one row, `@st.cache_data(ttl=300)`, raising on database errors so the page decides what to show.

- [ ] **Step 1: Write the failing tests**

```python
def test_ping_without_engine_reports_not_configured():
    assert ping(None) == PingResult(False, None, None, "DATABASE_URL is not set")

def test_ping_unreachable_database_fails_fast():
    started = time.monotonic()
    result = ping(make_engine("postgresql+psycopg://u:secret-pw@127.0.0.1:1/db"))
    assert result.ok is False and result.latency_ms is None and time.monotonic() - started < 5
    assert "secret-pw" not in (result.error or "")

@pytest.mark.db
def test_ping_reports_version_and_latency(migrated_db_url):
    result = ping(make_engine(migrated_db_url))
    assert result.ok and result.server_version.startswith("16.") and result.latency_ms >= 0

@pytest.mark.db
def test_last_ingestion_run_is_empty_then_latest(migrated_db_url, settings_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    clear_caches()  # get_settings, st.cache_data, st.cache_resource
    assert last_ingestion_run().empty
    insert_runs(migrated_db_url, count=2)
    clear_caches()
    assert last_ingestion_run()["run_id"].tolist() == [2]
```

Put `clear_caches()` in `tests/conftest.py`; `insert_runs` stays in the test module.

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement** `app/data/db.py` and `app/data/queries.py` (SQL: `SELECT run_id, started_at FROM ingestion_runs ORDER BY run_id DESC LIMIT 1`).
- [ ] **Step 4: Run the tests** — expected 4 passed.
- [ ] **Step 5: Commit** — `Add the database engine, ping and the last-run query`.

### Task 6: App shell and the Pipeline tiles

**Files:**
- Create: `app/main.py`, `app/components/__init__.py`, `app/components/layout.py`, `app/pages/overview.py`, `app/pages/timeline.py`, `app/pages/targets.py`, `app/pages/feature_explorer.py`, `app/pages/data_quality.py`, `app/pages/pipeline.py`, `tests/app/test_layout.py`, `tests/app/test_pipeline_page.py`, `tests/app/test_main.py`

**Interfaces:**
- Consumes: `get_settings()`, `page_render()`, `get_engine()`, `ping()`, `last_ingestion_run()`.
- Produces in `app/components/layout.py`: `env_banner(settings: Settings) -> None`, `sidebar_brand() -> None`, `sidebar_footer(settings: Settings) -> None`, `page_header(title: str, caption: str | None = None) -> None`, `kpi_tile(label: str, value: str, caption: str) -> None` (`st.container(border=True)` holding `st.metric` and `st.caption`), `coming_soon(requirement_ids: str) -> None` (one `st.info`: "This page arrives in a later release ({requirement_ids})."). In `app/main.py`: `PAGES: list[tuple[str, str, str, str]]` = (file, title, Material icon, slug) in this order: `overview.py` "Overview" `:material/dashboard:` overview; `timeline.py` "Timeline" `:material/timeline:` timeline; `targets.py` "Targets" `:material/my_location:` targets; `feature_explorer.py` "Feature explorer" `:material/query_stats:` feature_explorer; `data_quality.py` "Data quality" `:material/rule:` data_quality; `pipeline.py` "Pipeline" `:material/account_tree:` pipeline.
- Exact copy: banner `"{APP_ENV upper} environment · version {APP_VERSION} · not production data"` via `st.warning`, none in production (UI-10); footer `st.caption("{app_env} · version {app_version}")`; brand `":material/shield: **CIC-NIDS Dashboard**"` and caption `"Network intrusion analytics"`; page config `page_title="CIC-NIDS Dashboard"`, `layout="wide"`.
- Pipeline tiles, in one `st.columns(4)` row:
  - Environment: value `app_env`; caption `"{aws_region} · ECS on Fargate"`, or `"laptop · docker compose"` when local.
  - App version: value `app_version`; caption `"started {started_at:%Y-%m-%d %H:%M} UTC"`.
  - Database: `"Connected"` or `"Unreachable"`; caption `"RDS PostgreSQL {server_version} · {latency_ms} ms"` (no "RDS " when local), or the ping error.
  - Last ingestion: `"#{run_id}"` with `"started {…} UTC"`; `"—"` with `"no runs yet"`; `"—"` with `"runs table not available"` when the query raises (log the exception with `log_event(..., level="ERROR")`).
- `main.py` draws brand, navigation, banner and footer before `pg.run()`, and wraps `pg.run()` in `page_render(<slug>)`. An invalid `APP_ENV` shows `st.error` with the `ValueError` message and stops the script; the server keeps running.
- Placeholder pages call `page_header` and `coming_soon` with: Overview "UI-02, UI-08, UI-09"; Timeline "UI-03"; Targets "UI-04"; Feature explorer "UI-05"; Data quality "UI-06".

- [ ] **Step 1: Write the failing tests**

```python
# tests/app/test_layout.py
def _banner_app(env, version):
    from app.components.layout import env_banner
    from app.config import load_settings
    env_banner(load_settings({"APP_ENV": env, "APP_VERSION": version}))

def test_banner_shown_outside_production():
    at = AppTest.from_function(_banner_app, kwargs={"env": "staging", "version": "7c41e0b"}).run()
    assert at.warning[0].value == "STAGING environment · version 7c41e0b · not production data"

def test_no_banner_in_production():
    at = AppTest.from_function(_banner_app, kwargs={"env": "production", "version": "7c41e0b"}).run()
    assert len(at.warning) == 0

# tests/app/test_pipeline_page.py — APP_FILE paths are absolute, from REPO_ROOT
def test_tiles_with_unreachable_database(settings_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    clear_caches()
    at = AppTest.from_file(PIPELINE_PAGE, default_timeout=30).run()
    tiles = {m.label: m.value for m in at.metric}
    assert not at.exception
    assert tiles == {"Environment": "test", "App version": "abc1234", "Database": "Unreachable",
                     "Last ingestion": "—"}

@pytest.mark.db
def test_tiles_with_migrated_database(settings_env, migrated_db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    clear_caches()
    at = AppTest.from_file(PIPELINE_PAGE, default_timeout=30).run()
    tiles = {m.label: m.value for m in at.metric}
    assert tiles["Database"] == "Connected" and tiles["Last ingestion"] == "—"

# tests/app/test_main.py
def test_shell_runs_and_shows_banner(settings_env):
    at = AppTest.from_file(MAIN, default_timeout=30).run()
    assert not at.exception
    assert at.warning[0].value == "TEST environment · version abc1234 · not production data"

def test_shell_reports_invalid_app_env(settings_env, monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    clear_caches()
    at = AppTest.from_file(MAIN, default_timeout=30).run()
    assert "APP_ENV must be one of" in at.error[0].value
```

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement** `layout.py`, the six pages and `main.py`.
- [ ] **Step 4: Run all tests** — `python -m pytest`; expected everything passes (db tests with the compose database running).
- [ ] **Step 5: Look at it** — `streamlit run app/main.py` with `.env` values exported; open http://localhost:8501, check the banner, footer, six navigation entries and the four tiles at 1366 × 768.
- [ ] **Step 6: Commit** — `Add the app shell, banner and Pipeline tiles`.

### Task 7: Container image and local stack

**Files:**
- Create: `Dockerfile`, `.dockerignore`
- Modify: `docker-compose.yml` (add service `app`), `README.md` (section "Run it locally")

**Interfaces:**
- Produces: image that runs the start command by default and `python -m pipeline <command>` on demand.
- `Dockerfile`: base `python:3.12-slim-bookworm` pinned to the current patch tag; `WORKDIR /srv`; `ENV PYTHONPATH=/srv PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1`; install `requirements.txt` before copying code (layer cache); copy `.streamlit/`, `alembic.ini`, `migrations/`, `app/`, `pipeline/`; user `cicnids` with uid 10001; `EXPOSE 8501`; `CMD` is the start command in Global Constraints.
- `.dockerignore`: `.git`, `.github`, `docs`, `infra`, `scripts`, `tests`, `.env`, `local_s3`, `**/__pycache__`, `.pytest_cache`, `.ruff_cache`.
- Compose `app`: `build: .`, port 8501, `env_file: .env` with `required: false`, `DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/cicnids`, `depends_on: db: condition: service_healthy`.

- [ ] **Step 1: Build** — `docker build -t cicnids:local .`; expected success, and `docker run --rm cicnids:local id -u` prints `10001`.
- [ ] **Step 2: Health without a database** — `docker run -d --name cicnids-nodb -p 8502:8501 -e APP_ENV=test cicnids:local`; within 60 s `curl -s http://localhost:8502/_stcore/health` prints `ok`; remove the container.
- [ ] **Step 3: Full local stack** — `docker compose up -d --build`, `docker compose run --rm app python -m pipeline migrate` exits 0, `curl -s http://localhost:8501/_stcore/health` prints `ok`, and the Pipeline page shows Database "Connected" with Last ingestion "—" / "no runs yet".
- [ ] **Step 4: CLI help** — `docker run --rm cicnids:local python -m pipeline --help` lists `migrate` and `db-bootstrap`.
- [ ] **Step 5: Write the README section** (the five commands of report section 6.2, adapted: venv path, `pip install -e .`, compose, migrate, run).
- [ ] **Step 6: Commit** — `Add the Docker image and the local compose stack`.

### Task 8: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/pull_request_template.md`

**Interfaces:**
- Produces: four jobs whose names become the required checks: `lint`, `test`, `cfn-lint`, `image`.
- Triggers: `pull_request` to `main`, `workflow_dispatch`. Permissions `contents: read`. Concurrency group `ci-${{ github.ref }}`, cancel in progress. Runner `ubuntu-24.04`. Pin every action to its latest major tag, looked up with `gh api repos/<owner>/<action>/releases/latest` when this task runs.
  - `lint`: setup-python 3.12; install `requirements-dev.txt`; `ruff check .`; `ruff format --check .`; `actionlint`; `shellcheck` on `scripts/**/*.sh` when any exist.
  - `test`: service `postgres:16` (password `postgres`, port 5432, health `pg_isready`); env `TEST_ADMIN_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres`; install both requirement files and `pip install -e .`; `pytest --cov=pipeline --cov-report=term-missing --cov-fail-under=80`.
  - `cfn-lint`: `cfn-lint infra/*.yaml` when the folder has templates; otherwise print "no templates".
  - `image`: `docker build -t cicnids:ci .`; Trivy scan of `cicnids:ci` with `severity: CRITICAL,HIGH`, `ignore-unfixed: true`, `exit-code: 1`.
- PR template: the definition of done from report section 6.3, with "Hoàng has reviewed it" replaced by "CI is green".

- [ ] **Step 1: Write both files.**
- [ ] **Step 2: Lint the workflow** — `python -m actionlint`; expected no output.
- [ ] **Step 3: Commit** — `Add the CI workflow and pull request template`. (The first live run happens in Task 15.)

### Task 9: Bootstrap stack: OIDC and IAM

**Files:**
- Create: `infra/bootstrap.yaml`

**Interfaces:**
- Parameter `GitHubRepo`, default `Protein-17012006/SWE40006-CIC-NIDS-DevOps`.
- Resources:
  - `AWS::IAM::OIDCProvider` for `https://token.actions.githubusercontent.com`, client id `sts.amazonaws.com`.
  - Role `cicnids-cfn-exec`: trusted by `cloudformation.amazonaws.com`, managed policy `AdministratorAccess`.
  - GitHub roles, each trusting the provider with `aud = sts.amazonaws.com` and `StringLike` on `sub`:

| Role | `sub` | Permissions |
| --- | --- | --- |
| `cicnids-gha-build` | `repo:${GitHubRepo}:ref:refs/heads/*` | `ecr:GetAuthorizationToken` on `*`; push, pull and `DescribeImages` on repository `cic-nids` |
| `cicnids-gha-preview` | `repo:${GitHubRepo}:pull_request` | `CreateChangeSet`, `DescribeChangeSet`, `DeleteChangeSet`, `ListChangeSets`, `DescribeStacks`, `GetTemplateSummary` on `stack/cicnids-*`; `iam:PassRole` on `cicnids-cfn-exec` |
| `cicnids-gha-platform` | `repo:${GitHubRepo}:environment:platform` | `cloudformation:*` on `stack/cicnids-platform/*` and `stack/cicnids-databases/*`; `DescribeStacks` on `*`; `iam:PassRole` on `cicnids-cfn-exec` |
| `cicnids-gha-deploy-<env>`, four explicit resources | `repo:${GitHubRepo}:environment:<env>` | `cloudformation:*` on `stack/cicnids-<env>/*`; `DescribeStacks` on `*`; `iam:PassRole` on `cicnids-cfn-exec` (to `cloudformation.amazonaws.com`) and on `role/cicnids-<env>-*` (to `ecs-tasks.amazonaws.com`); `ecs:RunTask` on `task-definition/cicnids-<env>-job:*` and `cicnids-<env>-admin:*`; `ecs:DescribeTasks`, `ListTasks`, `DescribeServices`, `DescribeTaskDefinition`, `UpdateService`; `logs:GetLogEvents`, `FilterLogEvents` on `/cicnids/<env>`; `ecr:DescribeImages` on `cic-nids` |

- Outputs: every role ARN.

- [ ] **Step 1: Write the template.**
- [ ] **Step 2: Lint** — `python -m cfnlint infra/bootstrap.yaml`; expected no findings.
- [ ] **Step 3: Deploy from the laptop** (the one manual stack) — `aws cloudformation deploy --template-file infra/bootstrap.yaml --stack-name cicnids-bootstrap --capabilities CAPABILITY_NAMED_IAM --tags Project=cic-nids Environment=shared`; expected `Successfully created/updated stack`.
- [ ] **Step 4: Verify** — `aws iam get-role --role-name cicnids-gha-deploy-production --query Role.AssumeRolePolicyDocument` shows the `environment:production` subject.
- [ ] **Step 5: Commit** — `Add the bootstrap stack for GitHub OIDC and IAM`.

### Task 10: Platform stack

**Files:**
- Create: `infra/platform.yaml`

**Interfaces:**
- Parameters: `ContainerInsightsProd` (`enabled` | `disabled`, default `enabled`); `AlertEmail` (default empty; a condition creates the email subscription only when set).
- Resources: VPC `10.20.0.0/16` with DNS support and hostnames; public subnets `10.20.0.0/24` and `10.20.1.0/24` and private subnets `10.20.10.0/24` and `10.20.11.0/24` in the first two Availability Zones; internet gateway; public route table with `0.0.0.0/0` to the gateway; private route table with no internet route; S3 gateway endpoint on both route tables; ALB security group allowing TCP 80 and 8080–8082 from `0.0.0.0/0`; internet-facing ALB in the public subnets with idle timeout 300 s (Streamlit WebSockets); ECR repository `cic-nids` with immutable tags, scan on push and a lifecycle rule keeping the newest 30 images; ECS cluster `cicnids-prod` (Container Insights from the parameter) and `cicnids-nonprod` (disabled); SNS topic `cicnids-alerts` with a policy letting `budgets.amazonaws.com` and `cloudwatch.amazonaws.com` publish; budget `cicnids-credit` (COST, ANNUALLY, 200 USD) with ACTUAL > 50, 100 and 150 USD (absolute) notifications to the topic.
- Outputs, exported as `cicnids-platform-<Name>`: `VpcId`, `PublicSubnetIds` and `PrivateSubnetIds` (comma-joined), `AlbArn`, `AlbDnsName`, `AlbSecurityGroupId`, `EcrRepositoryUri`, `ProdClusterName`, `NonprodClusterName`, `AlertTopicArn`.

- [ ] **Step 1: Write the template.**
- [ ] **Step 2: Lint and validate** — `python -m cfnlint infra/platform.yaml` and `aws cloudformation validate-template --template-body file://infra/platform.yaml`; expected no findings, valid.
- [ ] **Step 3: Commit** — `Add the platform stack`. (infra.yml creates it in Task 15.)

### Task 11: Databases stack

**Files:**
- Create: `infra/databases.yaml`

**Interfaces:**
- Imports the private subnets and VPC from `cicnids-platform`.
- Resources: DB subnet group over the private subnets; security groups `ProdDbSecurityGroup` and `NonprodDbSecurityGroup` with no ingress (environment stacks add it); instances `cicnids-prod` and `cicnids-nonprod`: `postgres`, `EngineVersion: "16"`, `db.t4g.micro`, 20 GB `gp3`, encrypted, single-AZ, not publicly accessible, master user `cicnids_admin` with `ManageMasterUserPassword: true`, 7-day backups, auto minor upgrades, copy tags to snapshots, `DeletionPolicy` and `UpdateReplacePolicy` `Snapshot`.
- Outputs, exported as `cicnids-databases-<Name>`: `ProdEndpoint`, `ProdPort`, `ProdMasterSecretArn` (`!GetAtt <db>.MasterUserSecret.SecretArn`), `ProdSecurityGroupId`, and the same four with the `Nonprod` prefix.

- [ ] **Step 1: Write the template.**
- [ ] **Step 2: Lint and validate**, as in Task 10.
- [ ] **Step 3: Commit** — `Add the databases stack`.

### Task 12: Environment stack and parameter files

**Files:**
- Create: `infra/environment.yaml`, `infra/params/development.params`, `infra/params/test.params`, `infra/params/staging.params`, `infra/params/production.params`

**Interfaces:**
- Parameters: `EnvName` (the four names), `ListenerPort`, `DbTier` (`Prod` | `Nonprod`, used to build import names such as `cicnids-databases-${DbTier}Endpoint`), `ClusterName`, `AppCpu` (`256` | `512`), `AppMemory` (default `1024`), `AppImageTag`, `JobImageTag`, `DesiredCount` (default 1).
- Parameter files are `Key=Value` lines (read into `--parameter-overrides` by the deploy script):

| File | EnvName | ListenerPort | DbTier | ClusterName | AppCpu |
| --- | --- | --- | --- | --- | --- |
| development.params | development | 8082 | Nonprod | cicnids-nonprod | 256 |
| test.params | test | 8081 | Nonprod | cicnids-nonprod | 256 |
| staging.params | staging | 8080 | Nonprod | cicnids-nonprod | 512 |
| production.params | production | 80 | Prod | cicnids-prod | 512 |

- Resources:
  - Bucket `cicnids-${EnvName}-${AWS::AccountId}`: EventBridge notifications on, public access blocked, SSE-S3.
  - Log group `/cicnids/${EnvName}`, 14-day retention.
  - Secret `cicnids/${EnvName}/db`: template `{"username": "cicnids_<env>", "dbname": "cicnids_<env>", "host": <tier endpoint>, "port": <tier port>}`, generated `password` of 32 characters without punctuation. Secret `cicnids/${EnvName}/upload-password`: generated 24 characters without punctuation.
  - Task security group: TCP 8501 from the ALB security group. RDS ingress rule: TCP 5432 into the tier's DB security group from the task security group.
  - Target group: `ip` targets, HTTP 8501, health check `/_stcore/health`, matcher 200, interval 15 s, healthy 2, unhealthy 3, deregistration delay 30 s. Listener on `ListenerPort` forwarding to it.
  - Roles: `cicnids-${EnvName}-exec` (ECS task execution policy plus `GetSecretValue` on both environment secrets); `cicnids-${EnvName}-admin-exec` (the same plus the tier's master secret); `cicnids-${EnvName}-task` (`ListBucket` on the bucket, `GetObject` and `PutObject` on its objects).
  - Task definitions, all Fargate, logging to the log group with stream prefixes `app`, `job`, `admin`:
    - `cicnids-${EnvName}-app`: `AppCpu`/`AppMemory`; container `app` on port 8501, image `<EcrRepositoryUri>:${AppImageTag}`; env `APP_ENV`, `APP_VERSION=${AppImageTag}`, `AWS_REGION`, `S3_BUCKET`; secrets `DB_SECRET`, `UPLOAD_PASSWORD`.
    - `cicnids-${EnvName}-job`: 2048 CPU, 8192 MB; container `job`, image tag `${JobImageTag}`, the same env with `APP_VERSION=${JobImageTag}`; secret `DB_SECRET`; command `python -m pipeline --help`.
    - `cicnids-${EnvName}-admin`: 256 CPU, 512 MB; container `admin`, image tag `${JobImageTag}`; command `python -m pipeline db-bootstrap`; secrets `DB_SECRET`, `DB_MASTER_SECRET`; execution role `admin-exec`.
  - Service `cicnids-${EnvName}`: FARGATE in the public subnets with `AssignPublicIp: ENABLED`; `DesiredCount`; target group on container `app` port 8501; health check grace 60 s; minimum healthy 100%, maximum 200%; circuit breaker with rollback; depends on the listener.
- Outputs: `ServiceName`, `ClusterName`, `ListenerPort`, `TaskSecurityGroupId`, `BucketName`, `LogGroupName`, `JobTaskFamily`, `AdminTaskFamily`.

- [ ] **Step 1: Write the template and the four parameter files.**
- [ ] **Step 2: Lint and validate**, as in Task 10.
- [ ] **Step 3: Commit** — `Add the environment stack and parameter files`.

### Task 13: infra.yml

**Files:**
- Create: `.github/workflows/infra.yml`, `scripts/ci/lib.sh`, `scripts/ci/preview_changes.sh`

**Interfaces:**
- Produces in `scripts/ci/lib.sh` (sourced by every script; `set -euo pipefail`): `log <message>`; `stack_output <stack> <OutputKey>` (prints the value, fails when missing); `stack_exists <stack>` (exit status); `cfn_exec_role_arn` (`arn:aws:iam::${AWS_ACCOUNT_ID}:role/cicnids-cfn-exec`); `read_params <env>` (prints `infra/params/<env>.params` lines).
- `preview_changes.sh <stack> <template> [Key=Value...]`: creates a change set (`CREATE` when the stack is missing) with the execution role, waits, writes its changes as a Markdown table to `$GITHUB_STEP_SUMMARY`, deletes it (and a stack left in `REVIEW_IN_PROGRESS`).
- `infra.yml`: on `pull_request` and `push` to `main` touching `infra/bootstrap.yaml`, `infra/platform.yaml`, `infra/databases.yaml` or the workflow, plus `workflow_dispatch`. Permissions `id-token: write`, `contents: read`. Repository variables `AWS_ACCOUNT_ID`, `AWS_REGION`, optional `ALERT_EMAIL`.
  - Job `preview` (pull requests): role `cicnids-gha-preview`; preview `cicnids-platform` and `cicnids-databases`.
  - Job `deploy` (main and manual): `environment: platform`; role `cicnids-gha-platform`; `aws cloudformation deploy` of platform (passing `AlertEmail=${{ vars.ALERT_EMAIL }}`) then databases, with `--role-arn` the execution role, `--no-fail-on-empty-changeset` and the shared tags. A change to `bootstrap.yaml` only prints a notice that it is deployed from a laptop.

- [ ] **Step 1: Write the three files.**
- [ ] **Step 2: Lint** — `python -m actionlint` and `shellcheck scripts/ci/*.sh` (through Git Bash, or in CI); expected clean.
- [ ] **Step 3: Commit** — `Add the infra workflow with change-set previews`.

### Task 14: Deploy scripts and the CD, deploy and rollback workflows

Work on branch `feat/cd-pipeline`, so these workflows reach main through the first pull request (Task 15).

**Files:**
- Create: `scripts/ci/push_image.sh`, `scripts/ci/run_task.sh`, `scripts/ci/deploy_env.sh`, `scripts/ci/smoke_test.sh`, `.github/workflows/deploy.yml`, `.github/workflows/cd.yml`, `.github/workflows/rollback.yml`

**Interfaces:**
- Consumes: `lib.sh` functions; stack outputs from Tasks 10–12.
- Produces:
  - `push_image.sh <tag>`: when `ecr describe-images` finds the tag, prints "already pushed" and exits 0; otherwise builds, tags `<EcrRepositoryUri>:<tag>` and pushes.
  - `run_task.sh <env> <job|admin> [command...]`: runs the latest `cicnids-<env>-<kind>` task on the environment's cluster, public subnets, its task security group and `assignPublicIp=ENABLED`, with the command override on the container of the same name; waits until stopped (custom loop, 30 min limit); prints its log stream; exits with the container exit code.
  - `deploy_env.sh <env> <tag> [--skip-migrations]`: (1) `cloudformation deploy` of `cicnids-<env>` with the params file, `JobImageTag=<tag>` and `AppImageTag` = the stack's current value, or `<tag>` when the stack is new, `--role-arn`, `CAPABILITY_NAMED_IAM`, `--no-fail-on-empty-changeset`, tags; (2) if the service's desired count is 0, `ecs update-service --desired-count 1`; (3) `run_task.sh <env> admin`; (4) unless skipped, `run_task.sh <env> job python -m pipeline migrate`; (5) deploy again with `AppImageTag=<tag>`; (6) `smoke_test.sh <env> <tag>`. With `--skip-migrations` it also writes the newest ten ECR tags to the job summary.
  - `smoke_test.sh <env> <tag>`: `aws ecs wait services-stable`; fails unless the service's task definition image ends with `:<tag>`; `curl -fsS --retry 12 --retry-delay 10 --retry-all-errors http://<AlbDnsName>:<port>/_stcore/health` prints `ok`.
  - `deploy.yml` (`workflow_call`): inputs `environment`, `image_tag`, `run_migrations` (boolean, default true); one job with `environment: ${{ inputs.environment }}` (this is where production waits for approval) and concurrency `deploy-${{ inputs.environment }}` without cancelling; role `cicnids-gha-deploy-${{ inputs.environment }}`; runs `deploy_env.sh`.
  - `cd.yml`: on `push` to `main` with `paths-ignore: ["docs/**", "**/*.md"]`, and `workflow_dispatch`. Job `build` (role `cicnids-gha-build`) outputs `tag` = first 7 characters of `github.sha` and runs `push_image.sh`. Then `development` → `test` → `staging` → `production` through `deploy.yml`; on a manual run from a branch other than main, only `development` runs. Job `parity` writes a table of the image tag each environment's service runs.
  - `rollback.yml`: `workflow_dispatch` with `environment` (choice of the four) and `image_tag`; calls `deploy.yml` with `run_migrations: false`.

- [ ] **Step 1: Write the scripts and workflows.**
- [ ] **Step 2: Lint** — `python -m actionlint` and `shellcheck scripts/ci/*.sh`; expected clean.
- [ ] **Step 3: Commit on the branch** — `Add the CD, deploy and rollback workflows`.

### Task 15: Go live

**Files:**
- Create: `docs/runbook.md`
- Modify: `README.md` (environments and their URLs)

- [ ] **Step 1: Create the GitHub repository** (needs Hoàng's OK for a public repository): `gh repo create Protein-17012006/SWE40006-CIC-NIDS-DevOps --public --source . --remote origin --description "<description>"`, without pushing yet.
- [ ] **Step 2: Repository variables** — `gh variable set AWS_ACCOUNT_ID --body 834996123571` and `gh variable set AWS_REGION --body us-east-1`.
- [ ] **Step 3: Environments** — `gh api -X PUT repos/{owner}/{repo}/environments/<name>` for development, test and staging; for production and platform, add a required reviewer `{"type": "User", "id": <Protein-17012006's user id>}`.
- [ ] **Step 4: Push main** (everything except `feat/cd-pipeline`) — infra.yml starts; approve the `platform` deployment; expected cicnids-platform and cicnids-databases reach `CREATE_COMPLETE` (about 15 min). If a stack fails to create, read its events, fix the template in a commit, and re-run.
- [ ] **Step 5: First pull request** — push `feat/cd-pipeline` and open a pull request; expected the four CI checks pass (fix and push until they do).
- [ ] **Step 6: Protect main** — require a pull request, the checks `lint`, `test`, `cfn-lint`, `image` and an up-to-date branch, no required reviews, no force pushes.
- [ ] **Step 7: Merge** — cd.yml builds once and deploys development, test and staging; expected each smoke test passes and production waits for approval.
- [ ] **Step 8: Approve production** — expected production's smoke test passes, and the parity table shows the same tag in all four environments.
- [ ] **Step 9: Look at every environment** — `http://<AlbDnsName>:<port>/`: banner on 8082, 8081 and 8080, none on 80; the Pipeline page shows the environment, the tag, Database "Connected" and Last ingestion "—".
- [ ] **Step 10: Re-run the latest cd.yml run** — expected "already pushed", no stack changes, migrations no-op, all smoke tests pass (Review Focus 2).
- [ ] **Step 11: Stop development by hand** (`aws ecs update-service --cluster cicnids-nonprod --service cicnids-development --desired-count 0`) and re-run its deployment — expected the service returns to one task and the smoke test passes (Review Focus 4).
- [ ] **Step 12: Rollback drill** — merge a small visible change (the Pipeline page caption) to get a second tag into production, then run rollback.yml for production with the first tag; expected the earlier tag is back within 10 minutes (OPS-05), as shown by the smoke test and the parity table.
- [ ] **Step 13: Write `docs/runbook.md` and update the README** — first-time setup (bootstrap from a laptop, variables, environments, branch protection), how a release flows, rollback, stopping and starting an environment by hand, deleting every stack after grading. Merge through a pull request.

"""The end-to-end test, run as a job task in the test environment (build design section 7).

It resets the test database and bucket, then uploads every contract-test sample to raw/, so
the real path ingests them: S3, EventBridge, one job task per file. It waits for the runs,
checks what each one did, and renders every page with AppTest against what was loaded.
Because the samples drive it, a merged contract and its moved sample extend it by themselves.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
import yaml

from app.telemetry import first_line, log_event
from pipeline.contracts import Contract
from pipeline.load import TABLES
from pipeline.storage import Bucket, parse_raw_key

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "tests" / "contracts"
VIEWS = ROOT / "app" / "views"
BROKEN = "broken"
RESET_PREFIXES = ("raw/", "processed/", "quarantine/")
RUN_TIMEOUT_S = 600


@dataclass(frozen=True)
class Sample:
    path: Path
    key: str
    contract: str | None  # None for a file that must be quarantined
    missing: tuple[str, ...]  # the required fields a broken file lacks


@dataclass(frozen=True)
class Finished:
    key: str
    status: str
    message: str
    rows_loaded: int
    dataset_id: str


def samples(root: Path = SAMPLES) -> list[Sample]:
    """A contract folder's files load into that contract's dataset; each broken file is its own
    dataset at the top of raw/, like a one-off upload, and must be quarantined."""
    expected_path = root / BROKEN / "expected.yaml"
    expected = {}
    if expected_path.exists():
        expected = yaml.safe_load(expected_path.read_text(encoding="utf-8")) or {}
    items = []
    for path in root.glob("*/*.csv"):
        folder = path.parent.name
        if folder == BROKEN:
            missing = tuple(expected.get(path.name, {}).get("missing", []))
            items.append(Sample(path, f"raw/{path.name}", None, missing))
        else:
            items.append(Sample(path, f"raw/{folder}/{path.name}", folder, ()))
    return sorted(items, key=lambda s: s.key)


def db_now(engine: sa.Engine) -> datetime:
    """The database's clock, which also stamps the runs, so no clock skew between tasks."""
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT now()")).scalar_one()


def reset(engine: sa.Engine, bucket: Bucket) -> None:
    """Empty every data table (the schema stays at its revision) and the bucket's folders."""
    tables = ", ".join(TABLES)  # constants from pipeline.load, never input
    with engine.begin() as conn:
        conn.execute(sa.text(f"TRUNCATE {tables} RESTART IDENTITY"))
    for prefix in RESET_PREFIXES:
        bucket.delete_prefix(prefix)


def upload(bucket: Bucket, items: Sequence[Sample]) -> None:
    for item in items:
        bucket.upload(item.path, item.key)


_NEWEST_RUNS = sa.text(
    "SELECT DISTINCT ON (file_key) file_key, status, message, rows_loaded, dataset_id "
    "FROM ingestion_runs WHERE file_key = ANY(:keys) AND started_at >= :since "
    "ORDER BY file_key, run_id DESC"
)


def wait_for_runs(
    engine: sa.Engine,
    keys: Sequence[str],
    since: datetime,
    *,
    timeout_s: float = RUN_TIMEOUT_S,
    poll_s: float = 10,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Finished]:
    """Each key's newest run that started at or after since, once it is no longer running.
    Returns when every key has one, or with what it has once timeout_s has passed."""
    wanted = sorted(set(keys))
    deadline = time.monotonic() + timeout_s
    while True:
        with engine.connect() as conn:
            rows = conn.execute(_NEWEST_RUNS, {"keys": wanted, "since": since}).mappings().all()
        finished = {
            row["file_key"]: Finished(
                row["file_key"],
                row["status"],
                row["message"] or "",
                row["rows_loaded"] or 0,
                row["dataset_id"],
            )
            for row in rows
            if row["status"] != "running"
        }
        if len(finished) == len(wanted) or time.monotonic() >= deadline:
            return finished
        sleep(poll_s)


def _has_label(engine: sa.Engine, dataset_id: str) -> bool | None:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT has_label FROM datasets WHERE dataset_id = :id"), {"id": dataset_id}
        ).scalar_one_or_none()


def _loaded_problems(
    item: Sample, run: Finished, contract: Contract | None, engine: sa.Engine
) -> list[str]:
    if contract is None:
        return [f"{item.key}: no contract named {item.contract} in the image"]
    problems = []
    if run.rows_loaded <= 0:
        problems.append(f"{item.key}: no rows loaded")
    has_label = _has_label(engine, run.dataset_id)
    if has_label != contract.has_label:
        problems.append(f"{item.key}: has_label is {has_label}, expected {contract.has_label}")
    return problems


def _quarantine_problems(item: Sample, bucket: Bucket) -> list[str]:
    raw = parse_raw_key(item.key)
    problems = []
    if not bucket.exists(raw.report_key):
        problems.append(f"{item.key}: report missing")
    else:
        report = bucket.read_text(raw.report_key)
        problems += [
            f"{item.key}: the report does not name {field}"
            for field in item.missing
            if field not in report
        ]
    if not bucket.exists(raw.draft_key):
        problems.append(f"{item.key}: draft contract missing")
    return problems


def check(
    items: Sequence[Sample],
    finished: dict[str, Finished],
    contracts: Sequence[Contract],
    bucket: Bucket,
    engine: sa.Engine,
) -> list[str]:
    """One message per broken expectation, each starting with the sample's key."""
    by_name = {c.name: c for c in contracts}
    problems: list[str] = []
    for item in items:
        run = finished.get(item.key)
        if run is None:
            problems.append(f"{item.key}: no finished run")
            continue
        expected = "loaded" if item.contract else "quarantined"
        if run.status != expected:
            problems.append(f"{item.key}: {run.status}, expected {expected} ({run.message})")
            continue
        if item.contract:
            problems += _loaded_problems(item, run, by_name.get(item.contract), engine)
        else:
            problems += _quarantine_problems(item, bucket)
    return problems


def render_pages(dataset_ids: Sequence[str], views: Path = VIEWS) -> list[str]:
    """Run every page once per dataset under AppTest; a message for each page that raised,
    showed an error, or had a card that could not load its data."""
    from streamlit.testing.v1 import AppTest

    from app.components.filters import DATASET_KEY
    from app.components.layout import CARD_FAILED

    problems = []
    for dataset_id in dataset_ids:
        for view in sorted(views.glob("*.py")):
            where = f"{view.stem} on {dataset_id}"
            at = AppTest.from_file(str(view), default_timeout=60)
            at.session_state[DATASET_KEY] = dataset_id
            try:
                at.run()
            except Exception as exc:  # the page outran the timeout
                problems.append(f"{where}: {first_line(exc)}")
                continue
            if at.exception:
                problems.append(f"{where}: {at.exception[0].value}")
            elif at.error:
                problems.append(f"{where}: {at.error[0].value}")
            elif any(w.value == CARD_FAILED for w in at.warning):
                problems.append(f"{where}: {CARD_FAILED}")
    return problems


def _loaded_datasets(engine: sa.Engine) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                sa.text("SELECT dataset_id FROM datasets WHERE status = 'loaded' ORDER BY 1")
            ).scalars()
        )


def _log_checks(names: Sequence[str], problems: Sequence[str]) -> None:
    for name in names:
        mine = [p for p in problems if p.startswith(f"{name}:")]
        log_event("e2e_check", check=name, ok=not mine, detail="; ".join(mine))


def run(
    engine: sa.Engine,
    bucket: Bucket,
    contracts: Sequence[Contract],
    *,
    sleep: Callable[[float], None] = time.sleep,
    views: Path = VIEWS,
) -> list[str]:
    """The whole end-to-end test; returns every failed check's message (empty when all pass)."""
    started = time.perf_counter()
    since = db_now(engine)
    reset(engine, bucket)
    items = samples()
    upload(bucket, items)
    finished = wait_for_runs(engine, [item.key for item in items], since, sleep=sleep)
    ingest_problems = check(items, finished, contracts, bucket, engine)
    _log_checks([item.key for item in items], ingest_problems)

    datasets = _loaded_datasets(engine)
    page_problems = render_pages(datasets, views)
    pages = [f"{v.stem} on {d}" for d in datasets for v in sorted(views.glob("*.py"))]
    _log_checks(pages, page_problems)

    problems = ingest_problems + page_problems
    log_event(
        "e2e_summary",
        checks=len(items) + len(pages),
        failed=len(problems),
        duration_s=round(time.perf_counter() - started, 1),
    )
    return problems

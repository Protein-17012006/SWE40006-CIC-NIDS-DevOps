"""Ingest one raw file end to end (design section 5.2): match, clean, load or quarantine.

reconcile (design section 5.3) re-ingests the files a deployed contract now reads differently.
"""

import shutil
import time
import zlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

from app.data.fields import CANONICAL_FIELDS
from app.telemetry import log_event
from pipeline.accumulate import Aggregates, Deduplicator, Quality
from pipeline.clean import (
    CHUNK_ROWS,
    clean_chunk,
    extra_output_name,
    infer_extra_kinds,
    read_chunks,
    read_header,
)
from pipeline.contracts import Contract, Match, closest_contract, match_contract, missing_fields
from pipeline.draft import draft_contract, quarantine_report
from pipeline.load import (
    FileData,
    RunRecord,
    finish_run,
    latest_runs,
    mark_stale_runs,
    start_run,
)
from pipeline.storage import Bucket, RawFile, parse_raw_key

REJECT_THRESHOLD = 0.20
NO_ROWS = "The file has no data rows."


def _first_line(exc: BaseException) -> str:
    text = str(exc)
    return text.splitlines()[0] if text else ""


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def ingest_file(
    key: str,
    *,
    engine: sa.Engine,
    bucket: Bucket,
    contracts: Sequence[Contract],
    commit_sha: str,
    workdir: Path,
    chunk_rows: int = CHUNK_ROWS,
) -> RunRecord | None:
    """Record one run for the file at key; None (and no run) when key is not a raw CSV."""
    if parse_raw_key(key) is None:
        log_event("ingest_skipped", key=key, reason="not a CSV file under raw/")
        return None
    raw = parse_raw_key(bucket.resolve_key(key))
    started = time.perf_counter()
    run_id = start_run(engine, raw.dataset_id, raw.key, commit_sha)
    rundir = workdir / f"run-{run_id}"
    rundir.mkdir(parents=True, exist_ok=True)
    try:
        record, data = _process(raw, run_id, bucket, contracts, rundir, chunk_rows)
        finish_run(engine, run_id, record, data)
    except Exception as exc:
        record = RunRecord(
            status="failed", message=f"Failed: {type(exc).__name__}: {_first_line(exc)}"
        )
        try:
            finish_run(engine, run_id, record)
        except Exception as inner:  # the database may be what failed; the log still tells
            log_event("run_record_failed", level="ERROR", run_id=run_id, message=_first_line(inner))
        _log(record, run_id, raw, started, level="ERROR")
        raise
    finally:
        shutil.rmtree(rundir, ignore_errors=True)
    _log(record, run_id, raw, started)
    return record


def _log(record: RunRecord, run_id: int, raw: RawFile, started: float, level: str = "INFO") -> None:
    contract = None
    if record.contract_name:
        contract = f"{record.contract_name} v{record.contract_version}"
    log_event(
        "ingestion_run",
        level=level,
        run_id=run_id,
        dataset_id=raw.dataset_id,
        file_key=raw.key,
        contract=contract,
        status=record.status,
        rows_read=record.rows_read,
        rows_loaded=record.rows_loaded,
        rows_rejected=record.rows_rejected,
        new_columns=len(record.new_columns),
        duration_s=round(time.perf_counter() - started, 1),
        message=record.message,
    )


def _process(
    raw: RawFile,
    run_id: int,
    bucket: Bucket,
    contracts: Sequence[Contract],
    rundir: Path,
    chunk_rows: int,
) -> tuple[RunRecord, FileData | None]:
    path = rundir / "source.csv"
    bucket.download(raw.key, path)
    header = read_header(path)
    if not header:
        return _quarantine(raw, run_id, bucket, contracts, header, NO_ROWS, draft=False), None
    match = match_contract(header, contracts)
    if match is None:
        closest = closest_contract(header, contracts)
        if closest is None:
            reason = "No contract matches: no contracts are installed."
        else:
            missing = ", ".join(missing_fields(header, closest))
            reason = f"No contract matches: missing {missing} (closest: {_tag(closest)})."
        first = next(read_chunks(path, chunk_rows), pd.DataFrame())
        return _quarantine(raw, run_id, bucket, contracts, header, reason, first=first), None
    return _stream(raw, run_id, bucket, contracts, header, match, path, rundir, chunk_rows)


def _tag(contract: Contract) -> str:
    return f"{contract.name} v{contract.version}"


def _quarantine(
    raw: RawFile,
    run_id: int,
    bucket: Bucket,
    contracts: Sequence[Contract],
    header: list[str],
    reason: str,
    *,
    first: pd.DataFrame | None = None,
    draft: bool = True,
    unknown_labels: Counter[str] | None = None,
    **counts: object,
) -> RunRecord:
    report = quarantine_report(raw, run_id, reason, header, contracts, unknown_labels)
    bucket.put_text(raw.report_key, report, "text/markdown; charset=utf-8")
    draft_key = None
    if draft:
        text = draft_contract(
            raw.dataset_id, header, contracts, first if first is not None else pd.DataFrame()
        )
        bucket.put_text(raw.draft_key, text, "application/yaml; charset=utf-8")
        draft_key = raw.draft_key
    return RunRecord(
        status="quarantined",
        message=reason,
        source_columns=header,
        report_key=raw.report_key,
        draft_contract_key=draft_key,
        **counts,
    )


def _stream(
    raw: RawFile,
    run_id: int,
    bucket: Bucket,
    contracts: Sequence[Contract],
    header: list[str],
    match: Match,
    path: Path,
    rundir: Path,
    chunk_rows: int,
) -> tuple[RunRecord, FileData | None]:
    contract = match.contract
    aggregates = Aggregates(seed=zlib.crc32(raw.key.encode("utf-8")))
    quality, dedup = Quality(), Deduplicator()
    rows_read = rejected = duplicates = 0
    unknown: Counter[str] = Counter()
    kinds, first, parts = None, None, []
    for chunk in read_chunks(path, chunk_rows):
        if kinds is None:
            kinds, first = infer_extra_kinds(chunk, match.extras), chunk
        cleaned = clean_chunk(chunk, match, kinds)
        kept, dropped = dedup.drop(cleaned.frame)
        rows_read += cleaned.rows_in
        rejected += cleaned.rejected
        duplicates += dropped
        unknown.update(cleaned.unknown_labels)
        aggregates.add(kept)
        quality.add(cleaned, kept, dropped)
        if len(kept):
            part = rundir / f"part-{len(parts):04d}.parquet"
            kept.to_parquet(part, index=False)
            parts.append(part)

    counts = {
        "contract_name": contract.name,
        "contract_version": contract.version,
        "rows_read": rows_read,
        "rows_rejected": rejected,
        "new_columns": match.new_columns,
    }
    if aggregates.rows == 0 and rejected == 0:
        record = _quarantine(raw, run_id, bucket, contracts, header, NO_ROWS, draft=False, **counts)
        return record, None
    share = rejected / rows_read
    if aggregates.rows == 0 or share > REJECT_THRESHOLD:
        reason = f"{share:.1%} of rows failed validation with {_tag(contract)}."
        record = _quarantine(
            raw,
            run_id,
            bucket,
            contracts,
            header,
            reason,
            first=first,
            unknown_labels=unknown,
            **counts,
        )
        return record, None

    bucket.delete_prefix(raw.processed_prefix)
    for part in parts:
        bucket.upload(part, raw.processed_prefix + part.name)
    fields = [f.name for f in CANONICAL_FIELDS if f.name in match.mapping]
    if contract.has_label:
        fields.insert(fields.index("label") + 1, "attack_category")
    data = FileData(
        hourly=aggregates.hourly(),
        ports=aggregates.ports(),
        sample=aggregates.sample(),
        steps=quality.steps(),
        columns=quality.columns(),
        fields=fields,
        extra_fields=[extra_output_name(c) for c in match.extras],
        has_label=contract.has_label,
    )
    message = _loaded_message(aggregates.rows, rows_read, contract, rejected, unknown, duplicates)
    if match.new_columns:
        count = _plural(len(match.new_columns), "new column")
        message += f" {count}: {', '.join(match.new_columns)}."
    record = RunRecord(
        status="loaded",
        message=message,
        rows_loaded=aggregates.rows,
        source_columns=header,
        first_ts=aggregates.first_ts,
        last_ts=aggregates.last_ts,
        **counts,
    )
    return record, data


def _loaded_message(
    loaded: int,
    read: int,
    contract: Contract,
    rejected: int,
    unknown: Counter[str],
    duplicates: int,
) -> str:
    text = f"Loaded {loaded:,} of {read:,} rows with {_tag(contract)}."
    if duplicates:
        text += f" Removed {_plural(duplicates, 'duplicate row')}."
    if rejected:
        reasons = [f"unknown label {label} ({n:,})" for label, n in unknown.most_common()]
        checks = rejected - sum(unknown.values())
        if checks:
            reasons.append(f"failed checks ({checks:,})")
        text += f" Rejected {_plural(rejected, 'row')}: {', '.join(reasons)}."
    return text


@dataclass
class ReconcileSummary:
    reingested: list[str] = field(default_factory=list)
    skipped: int = 0
    stale_failed: int = 0
    missing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return (
            f"re-ingested {_plural(len(self.reingested), 'file')}, skipped {self.skipped:,}, "
            f"{len(self.missing):,} missing, {len(self.failed):,} failed, "
            f"{_plural(self.stale_failed, 'stale run')} marked failed"
        )


def reconcile(
    *,
    engine: sa.Engine,
    bucket: Bucket,
    contracts: Sequence[Contract],
    commit_sha: str,
    workdir: Path,
) -> ReconcileSummary:
    """Re-ingest each file whose stored header now matches a different contract or version."""
    summary = ReconcileSummary(stale_failed=mark_stale_runs(engine))
    for run in latest_runs(engine):
        candidate = None
        if run.status in ("loaded", "quarantined") and run.source_columns:
            candidate = match_contract(run.source_columns, contracts)
        same = candidate and (candidate.contract.name, candidate.contract.version) == (
            run.contract_name,
            run.contract_version,
        )
        if candidate is None or same:
            summary.skipped += 1
            continue
        if not bucket.exists(run.file_key):
            log_event("reconcile_missing", level="WARNING", file_key=run.file_key)
            summary.missing.append(run.file_key)
            continue
        try:
            ingest_file(
                run.file_key,
                engine=engine,
                bucket=bucket,
                contracts=contracts,
                commit_sha=commit_sha,
                workdir=workdir,
            )
        except Exception:  # already recorded and logged by ingest_file; try the next file
            summary.failed.append(run.file_key)
        else:
            summary.reingested.append(run.file_key)
    return summary

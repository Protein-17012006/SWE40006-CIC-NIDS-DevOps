"""Read a CSV in text chunks, then clean, type and validate each chunk against its contract.

Every value is read as text, so a repeated header row or an "Infinity" string never breaks
the numeric parsing; the cleaning steps decide what each value becomes (ING-03, ING-04).
"""

import csv
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
import pandera.pandas as pa

from app.data.fields import ATTACK_CATEGORIES, CANONICAL_FIELDS, FIELD_NAMES
from pipeline.contracts import Contract, Match, normalise_header

CHUNK_ROWS = 100_000
STEPS: tuple[str, ...] = (
    "duplicates_removed",
    "infinite_set_to_null",
    "missing_kept_as_null",
    "repeated_headers_dropped",
    "labels_trimmed",
)
_INFINITE = frozenset({"inf", "-inf", "+inf", "infinity", "-infinity", "+infinity"})
_MISSING = frozenset({"", "nan"})
_KINDS = {f.name: f.kind for f in CANONICAL_FIELDS}
_RESERVED = FIELD_NAMES | {"attack_category"}
_INT_LIMIT = 2**53


def read_header(path: Path) -> list[str]:
    """The header as written, without a byte-order mark; empty for an empty file."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [c.replace("﻿", "") for c in next(csv.reader(f), [])]


def read_chunks(path: Path, chunk_rows: int = CHUNK_ROWS) -> Iterator[pd.DataFrame]:
    """Chunks of text values (empty cells as ""), with normalised column names."""
    header = read_header(path)
    if not header:
        return
    names = normalise_header(header)
    reader = pd.read_csv(
        path, dtype=str, keep_default_na=False, chunksize=chunk_rows, encoding="utf-8-sig"
    )
    for chunk in reader:
        if len(chunk):
            chunk.columns = names
            yield chunk


def extra_output_name(column: str) -> str:
    """An extra column named like a canonical field is stored as <name>_extra."""
    return f"{column}_extra" if column in _RESERVED else column


def _normalised(values: pd.Series) -> pd.Series:
    text = values.str.strip().str.lower()
    return text.str.replace(r"[^a-z0-9]+", "_", regex=True).str.strip("_")


def infer_extra_kinds(
    chunk: pd.DataFrame, extras: Sequence[str]
) -> dict[str, Literal["numeric", "text"]]:
    """Numeric when every other value of the first chunk parses as a number."""
    kinds: dict[str, Literal["numeric", "text"]] = {}
    for column in extras:
        values = chunk[column].str.strip()
        lower = values.str.lower()
        ignore = lower.isin(_MISSING) | lower.isin(_INFINITE) | (_normalised(values) == column)
        parsed = pd.to_numeric(values[~ignore], errors="coerce")
        kinds[column] = "numeric" if parsed.notna().all() else "text"
    return kinds


def build_schema(contract: Contract) -> pa.DataFrameSchema:
    checks = {
        "dst_port": [pa.Check.in_range(0, 65535)],
        "protocol": [pa.Check.in_range(0, 255)],
        "flow_duration_us": [pa.Check.ge(0)],
        "fwd_packets": [pa.Check.ge(0)],
        "bwd_packets": [pa.Check.ge(0)],
        "fwd_bytes": [pa.Check.ge(0)],
        "bwd_bytes": [pa.Check.ge(0)],
    }
    columns = {}
    for field in CANONICAL_FIELDS:
        if field.name in contract.fields:
            not_null = field.required or field.name in ("timestamp", "label")
            columns[field.name] = pa.Column(checks=checks.get(field.name), nullable=not not_null)
    if contract.has_label:
        columns["attack_category"] = pa.Column(
            checks=[pa.Check.isin(ATTACK_CATEGORIES)], nullable=False
        )
    return pa.DataFrameSchema(columns, strict=False)


@dataclass
class CleanChunk:
    frame: pd.DataFrame
    rows_in: int
    rejected: int
    steps: Counter[str]
    unknown_labels: Counter[str]
    nulls: Counter[str]
    infinite: Counter[str]


@dataclass
class _Parsed:
    values: pd.Series
    missing: pd.Series
    infinite: pd.Series | None


def _parse_numeric(raw: pd.Series, scale: float = 1.0) -> _Parsed:
    text = raw.str.strip()
    lower = text.str.lower()
    infinite, missing = lower.isin(_INFINITE), lower.isin(_MISSING)
    masked = text.mask(infinite | missing)
    try:  # a direct cast is several times faster; it fails only when a value is not a number
        values = masked.astype("Float64")
    except (TypeError, ValueError):
        values = pd.to_numeric(masked, errors="coerce").astype("Float64")
    if scale != 1.0:
        values = values * scale
    return _Parsed(values, missing, infinite)


def _parse_text(raw: pd.Series) -> _Parsed:
    text = raw.str.strip()
    missing = text.str.lower().isin(_MISSING)
    return _Parsed(text.mask(missing).astype("string"), missing, None)


def _parse_field(raw: pd.Series, field: str, contract: Contract) -> _Parsed:
    kind = _KINDS[field]
    if kind == "text":
        return _parse_text(raw)
    if kind == "datetime":
        text = _parse_text(raw)
        stamps = pd.to_datetime(text.values, format=contract.timestamp_format, errors="coerce")
        return _Parsed(stamps.astype("datetime64[ns]"), text.missing, None)
    parsed = _parse_numeric(raw, contract.fields[field].scale)
    if kind == "integer":
        values = parsed.values
        integral = ((values % 1 == 0) & (values.abs() < _INT_LIMIT)).fillna(False)
        parsed.values = values.where(integral).round().astype("Int64")
    return parsed


def _repeated_headers(chunk: pd.DataFrame, match: Match) -> pd.Series:
    """Rows where at least half the values, normalised, equal their column's name."""
    probe = match.mapping["dst_port"]
    candidates = _normalised(chunk[probe]) == probe
    if not candidates.any():
        return candidates
    rows = chunk[candidates]
    same = sum((_normalised(rows[c]) == c).astype(int) for c in chunk.columns)
    return candidates & (same >= len(chunk.columns) / 2).reindex(chunk.index, fill_value=False)


def clean_chunk(chunk: pd.DataFrame, match: Match, extra_kinds: Mapping[str, str]) -> CleanChunk:
    contract = match.contract
    steps: Counter[str] = Counter(dict.fromkeys(STEPS, 0))
    rows_in = len(chunk)
    chunk = chunk.reset_index(drop=True)
    headers = _repeated_headers(chunk, match)
    steps["repeated_headers_dropped"] = int(headers.sum())
    chunk = chunk[~headers].reset_index(drop=True)

    parsed: dict[str, _Parsed] = {}
    for field in (f.name for f in CANONICAL_FIELDS if f.name in match.mapping):
        parsed[field] = _parse_field(chunk[match.mapping[field]], field, contract)
    for column in match.extras:
        if extra_kinds.get(column) == "numeric":
            parsed[extra_output_name(column)] = _parse_numeric(chunk[column])
        else:
            parsed[extra_output_name(column)] = _parse_text(chunk[column])

    nulls: Counter[str] = Counter()
    infinite: Counter[str] = Counter()
    any_missing = pd.Series(False, index=chunk.index)
    any_infinite = pd.Series(False, index=chunk.index)
    for name, p in parsed.items():
        if p.missing.any():
            nulls[name] = int(p.missing.sum())
            any_missing |= p.missing
        if p.infinite is not None and p.infinite.any():
            infinite[name] = int(p.infinite.sum())
            any_infinite |= p.infinite
    steps["missing_kept_as_null"] = int(any_missing.sum())
    steps["infinite_set_to_null"] = int(any_infinite.sum())

    frame = pd.DataFrame({name: p.values for name, p in parsed.items()}, index=chunk.index)
    unknown = pd.Series(False, index=chunk.index)
    unknown_labels: Counter[str] = Counter()
    if contract.has_label:
        raw_label = chunk[match.mapping["label"]]
        steps["labels_trimmed"] = int(
            (raw_label.str.len() != raw_label.str.strip().str.len()).sum()
        )
        category = frame["label"].map(contract.label_map).astype("string")
        unknown = (frame["label"].notna() & category.isna()).fillna(False).astype(bool)
        unknown_labels = Counter(frame.loc[unknown, "label"].tolist())
        position = list(frame.columns).index("label") + 1
        frame.insert(position, "attack_category", category)

    failed = _failed_rows(build_schema(contract), frame[~unknown])
    rejected = unknown | frame.index.isin(failed)
    kept = frame[~rejected].reset_index(drop=True)
    return CleanChunk(kept, rows_in, int(rejected.sum()), steps, unknown_labels, nulls, infinite)


def _failed_rows(schema: pa.DataFrameSchema, frame: pd.DataFrame) -> set[int]:
    try:
        schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        index = exc.failure_cases["index"].dropna()
        return {int(i) for i in index}
    return set()

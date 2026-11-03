"""Judge a Locust run from its CSV statistics: python -m scripts.load_verdict STATS FAILURES.

Any failed request fails the deployment (NFR-02). A slow 95th percentile only warns: the
network between GitHub's runners and AWS varies, and a slow minute is not a fault in the
release. Prints a Markdown summary, then one GitHub annotation per note.
"""

import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

P95_LIMIT_MS = 2000
_SERVER_ERROR = re.compile(r"\b5\d\d\b")


@dataclass
class Verdict:
    requests: int
    failures: int
    server_errors: int
    p95_ms: float | None
    ok: bool
    notes: list[str] = field(default_factory=list)


def _aggregated(stats_csv: Path) -> dict[str, str] | None:
    if not stats_csv.exists():
        return None
    with stats_csv.open(newline="", encoding="utf-8") as f:
        return next((row for row in csv.DictReader(f) if row.get("Name") == "Aggregated"), None)


def _server_errors(failures_csv: Path) -> int:
    if not failures_csv.exists():
        return 0
    with failures_csv.open(newline="", encoding="utf-8") as f:
        return sum(
            int(row["Occurrences"])
            for row in csv.DictReader(f)
            if _SERVER_ERROR.search(row.get("Error", ""))
        )


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text else None
    except ValueError:  # Locust writes N/A for a percentile it has no data for
        return None


def verdict(stats_csv: Path, failures_csv: Path, *, p95_limit_ms: float = P95_LIMIT_MS) -> Verdict:
    row = _aggregated(stats_csv)
    if row is None:
        return Verdict(0, 0, 0, None, False, ["Locust wrote no statistics"])
    requests, failures = int(row["Request Count"]), int(row["Failure Count"])
    p95 = _number(row.get("95%"))
    server_errors = _server_errors(failures_csv)
    notes = []
    if requests == 0:
        notes.append("Locust sent no requests")
    if failures:
        noun = "request" if failures == 1 else "requests"
        notes.append(f"{failures:,} {noun} failed, {server_errors:,} of them with a 5xx")
    if requests and p95 is not None and p95 > p95_limit_ms:
        notes.append(f"p95 {p95:,.0f} ms is above {p95_limit_ms:,.0f} ms")
    return Verdict(requests, failures, server_errors, p95, requests > 0 and not failures, notes)


def summary(v: Verdict) -> str:
    p95 = "—" if v.p95_ms is None else f"{v.p95_ms:,.0f}"
    lines = [
        "### Load test",
        "",
        "| Requests | Failures | 5xx | p95 (ms) |",
        "| --- | --- | --- | --- |",
        f"| {v.requests:,} | {v.failures:,} | {v.server_errors:,} | {p95} |",
    ]
    lines += ["", *(f"- {note}" for note in v.notes)] if v.notes else []
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m scripts.load_verdict STATS_CSV FAILURES_CSV", file=sys.stderr)
        return 2
    v = verdict(Path(args[0]), Path(args[1]))
    print(summary(v), end="")
    level = "warning" if v.ok else "error"
    for note in v.notes:
        print(f"::{level}::{note}")
    return 0 if v.ok else 1


if __name__ == "__main__":
    sys.exit(main())

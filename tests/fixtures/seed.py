"""The fixture the dashboard's page tests read: a labelled dataset over two capture days, an
unlabelled one-day file with two new columns, and one quarantined file.

Every run goes through pipeline.load, so the tables hold what ingestion would write. On a laptop,
`python -m tests.fixtures.seed` seeds DATABASE_URL; it refuses any APP_ENV but local and test.
"""

from datetime import date, datetime

import pandas as pd
import sqlalchemy as sa

from pipeline.accumulate import SAMPLE_COLUMNS, ColumnIssue
from pipeline.load import FileData, RunRecord, finish_run, start_run

LABELLED = "cse-cic-ids2018"
UNLABELLED = "simulated-real-traffic-01"
BROKEN = "broken"
COMMIT = "seed000"

FEB_14 = "raw/cse-cic-ids2018/Wednesday-14-02-2018.csv"
FEB_21 = "raw/cse-cic-ids2018/Wednesday-21-02-2018.csv"
SIMULATED = "raw/simulated-real-traffic-01.csv"
MISSING_DST_PORT = "raw/broken/missing-dst-port.csv"

BASELINE_HEADER = [
    "dst_port", "protocol", "timestamp", "flow_duration", "tot_fwd_pkts", "tot_bwd_pkts",
    "totlen_fwd_pkts", "totlen_bwd_pkts", "flow_byts_s", "flow_pkts_s", "fwd_pkt_len_max",
    "bwd_psh_flags", "src_ip", "dst_ip", "label",
]  # fmt: skip
SIMULATED_HEADER = [
    "destination_port", "protocol", "timestamp", "flow_duration", "total_fwd_packets",
    "total_backward_packets", "total_length_of_fwd_packets", "total_length_of_bwd_packets",
    "pkt_entropy", "geo_country",
]  # fmt: skip
LABELLED_FIELDS = [
    "timestamp", "dst_port", "protocol", "flow_duration_us", "fwd_packets", "bwd_packets",
    "fwd_bytes", "bwd_bytes", "flow_bytes_per_s", "flow_packets_per_s", "src_ip", "dst_ip",
    "label", "attack_category",
]  # fmt: skip
UNLABELLED_FIELDS = LABELLED_FIELDS[:8]

CATEGORY = {
    "Benign": "Benign",
    "FTP-BruteForce": "Brute force",
    "SSH-Bruteforce": "Brute force",
    "Bot": "Botnet",
    "Brute Force -Web": "Web attack",
    "DDOS attack-HOIC": "DDoS",
    "DoS attacks-Hulk": "DoS",
    "Infilteration": "Infiltration",
}

# (capture day, hour, label, flows); a None label is the unlabelled file
HOURLY = {
    FEB_14: [
        (date(2018, 2, 14), 9, "Benign", 1000),
        (date(2018, 2, 14), 10, "Benign", 1000),
        (date(2018, 2, 14), 10, "FTP-BruteForce", 400),
        (date(2018, 2, 14), 11, "Benign", 500),
        (date(2018, 2, 14), 11, "SSH-Bruteforce", 300),
        (date(2018, 2, 14), 14, "Bot", 200),
        (date(2018, 2, 14), 15, "Brute Force -Web", 5),
    ],
    FEB_21: [
        (date(2018, 2, 21), 9, "Benign", 900),
        (date(2018, 2, 21), 14, "Benign", 200),
        (date(2018, 2, 21), 14, "DDOS attack-HOIC", 2000),
        (date(2018, 2, 21), 15, "DoS attacks-Hulk", 600),
        (date(2018, 2, 21), 16, "Infilteration", 50),
    ],
    SIMULATED: [
        (date(2018, 3, 2), 9, None, 300),
        (date(2018, 3, 2), 10, None, 500),
        (date(2018, 3, 2), 11, None, 200),
    ],
}

# (capture day, category, protocol, destination port, flows); port -1 is the capped "other"
PORTS = {
    FEB_14: [
        (date(2018, 2, 14), "Benign", 6, 443, 1500),
        (date(2018, 2, 14), "Benign", 17, 53, 900),
        (date(2018, 2, 14), "Benign", 1, 0, 100),
        (date(2018, 2, 14), "Brute force", 6, 21, 400),
        (date(2018, 2, 14), "Brute force", 6, 22, 300),
        (date(2018, 2, 14), "Botnet", 6, 8080, 198),
        (date(2018, 2, 14), "Botnet", 6, 80, 2),
        (date(2018, 2, 14), "Web attack", 6, 80, 5),
    ],
    FEB_21: [
        (date(2018, 2, 21), "Benign", 6, 443, 700),
        (date(2018, 2, 21), "Benign", 17, 53, 350),
        (date(2018, 2, 21), "Benign", 6, -1, 50),
        (date(2018, 2, 21), "DDoS", 6, 80, 1990),
        (date(2018, 2, 21), "DDoS", 17, 53, 10),
        (date(2018, 2, 21), "DoS", 6, 80, 600),
        (date(2018, 2, 21), "Infiltration", 6, 445, 30),
        (date(2018, 2, 21), "Infiltration", 6, 3389, 15),
        (date(2018, 2, 21), "Infiltration", 6, -1, 5),
    ],
    SIMULATED: [
        (date(2018, 3, 2), None, 6, 443, 500),
        (date(2018, 3, 2), None, 6, 80, 300),
        (date(2018, 3, 2), None, 17, 53, 150),
        (date(2018, 3, 2), None, 6, 22, 50),
    ],
}

# Five sampled flows per group: (ts, label, category, protocol, port, duration base in µs)
SAMPLE_GROUPS = {
    FEB_14: [
        (datetime(2018, 2, 14, 9), "Benign", "Benign", 6, 443, 10_000),
        (datetime(2018, 2, 14, 10), "FTP-BruteForce", "Brute force", 6, 21, 3_000),
        (datetime(2018, 2, 14, 14), "Bot", "Botnet", 6, 8080, 500),
        (datetime(2018, 2, 14, 15), "Brute Force -Web", "Web attack", 6, 80, 1_000_000),
    ],
    FEB_21: [
        (datetime(2018, 2, 21, 14), "DDOS attack-HOIC", "DDoS", 6, 80, 2_000),
        (datetime(2018, 2, 21, 15), "DoS attacks-Hulk", "DoS", 6, 80, 1_000),
        (datetime(2018, 2, 21, 16), "Infilteration", "Infiltration", 6, 445, 100),
    ],
    SIMULATED: [(datetime(2018, 3, 2, 9), None, None, 6, 443, 4_000)],
}

NO_STEPS = {
    "duplicates_removed": 0,
    "infinite_set_to_null": 0,
    "missing_kept_as_null": 0,
    "repeated_headers_dropped": 0,
    "labels_trimmed": 0,
}


def _hourly(key: str) -> pd.DataFrame:
    rows = [
        (datetime(day.year, day.month, day.day, hour), label, CATEGORY.get(label), flows)
        for day, hour, label, flows in HOURLY[key]
    ]
    return pd.DataFrame(rows, columns=["hour", "label", "attack_category", "flows"])


def _ports(key: str) -> pd.DataFrame:
    columns = ["day", "attack_category", "protocol", "dst_port", "flows"]
    return pd.DataFrame(PORTS[key], columns=columns)


def _sample(key: str) -> pd.DataFrame:
    rows = []
    for ts, label, category, protocol, port, base in SAMPLE_GROUPS[key]:
        for i in range(1, 6):
            bwd_packets = (0, 0, 1, 2, 3)[i - 1]
            labelled = label is not None
            row = {
                "ts": ts,
                "label": label,
                "attack_category": category,
                "dst_port": port,
                "protocol": protocol,
                "flow_duration_us": float(base * i),
                "fwd_packets": i,
                "bwd_packets": bwd_packets,
                "fwd_bytes": float(100 * i),
                "bwd_bytes": float(50 * bwd_packets),
                "flow_bytes_per_s": float(1000 * i) if labelled else None,
                "flow_packets_per_s": float(10 * i) if labelled else None,
                "src_ip": None,
                "dst_ip": None,
                "extras": (
                    {"bwd_psh_flags": 0, "fwd_pkt_len_max": 10 * i}
                    if labelled
                    else {"pkt_entropy": float(i), "geo_country": "VN"}
                ),
            }
            rows.append(row)
    return pd.DataFrame(rows, columns=[*SAMPLE_COLUMNS, "extras"])


def _baseline_issues(infinite: int, nulls: int) -> list[ColumnIssue]:
    return [
        ColumnIssue("bwd_psh_flags", 0, 0, "constant, hidden"),
        ColumnIssue("flow_bytes_per_s", nulls, infinite, "infinite set to null"),
    ]


def _baseline_data(key: str, steps: dict[str, int], issues: list[ColumnIssue]) -> FileData:
    return FileData(
        hourly=_hourly(key),
        ports=_ports(key),
        sample=_sample(key),
        steps=steps,
        columns=issues,
        fields=LABELLED_FIELDS,
        extra_fields=["bwd_psh_flags", "fwd_pkt_len_max"],
        has_label=True,
    )


def _run(
    engine: sa.Engine, dataset_id: str, key: str, record: RunRecord, data: FileData | None
) -> None:
    run_id = start_run(engine, dataset_id, key, COMMIT)
    finish_run(engine, run_id, record, data)


def seed(engine: sa.Engine) -> None:
    """Load the five runs, in order, into a migrated and empty database."""
    _run(
        engine,
        LABELLED,
        FEB_14,
        RunRecord(
            status="loaded",
            message="Loaded 3,405 of 3,500 rows with cse-cic-ids2018 v1. "
            "Removed 50 duplicate rows. Rejected 45 rows.",
            contract_name="cse-cic-ids2018",
            contract_version=1,
            rows_read=3500,
            rows_loaded=3405,
            rows_rejected=45,
            source_columns=BASELINE_HEADER,
            first_ts=datetime(2018, 2, 14, 9),
            last_ts=datetime(2018, 2, 14, 15, 59),
        ),
        _baseline_data(
            FEB_14,
            {
                "duplicates_removed": 50,
                "infinite_set_to_null": 12,
                "missing_kept_as_null": 7,
                "repeated_headers_dropped": 1,
                "labels_trimmed": 0,
            },
            _baseline_issues(infinite=12, nulls=7),
        ),
    )
    _run(
        engine,
        LABELLED,
        FEB_21,
        RunRecord(status="failed", message="Failed: the task stopped before the run finished."),
        None,
    )
    _run(
        engine,
        LABELLED,
        FEB_21,
        RunRecord(
            status="loaded",
            message="Loaded 3,750 of 3,800 rows with cse-cic-ids2018 v1. "
            "Removed 50 duplicate rows.",
            contract_name="cse-cic-ids2018",
            contract_version=1,
            rows_read=3800,
            rows_loaded=3750,
            source_columns=BASELINE_HEADER,
            first_ts=datetime(2018, 2, 21, 9),
            last_ts=datetime(2018, 2, 21, 16, 59),
        ),
        _baseline_data(
            FEB_21,
            {**NO_STEPS, "duplicates_removed": 50, "infinite_set_to_null": 8},
            _baseline_issues(infinite=8, nulls=0),
        ),
    )
    _run(
        engine,
        UNLABELLED,
        SIMULATED,
        RunRecord(
            status="loaded",
            message="Loaded 1,000 of 1,000 rows with simulated-real-traffic v1. "
            "2 new columns: pkt_entropy, geo_country.",
            contract_name="simulated-real-traffic",
            contract_version=1,
            rows_read=1000,
            rows_loaded=1000,
            source_columns=SIMULATED_HEADER,
            new_columns=["pkt_entropy", "geo_country"],
            first_ts=datetime(2018, 3, 2, 9),
            last_ts=datetime(2018, 3, 2, 11, 59),
        ),
        FileData(
            hourly=_hourly(SIMULATED),
            ports=_ports(SIMULATED),
            sample=_sample(SIMULATED),
            steps=dict(NO_STEPS),
            columns=[],
            fields=UNLABELLED_FIELDS,
            extra_fields=["pkt_entropy", "geo_country"],
            has_label=False,
        ),
    )
    _run(
        engine,
        BROKEN,
        MISSING_DST_PORT,
        RunRecord(
            status="quarantined",
            message="1 required field not found: dst_port.",
            rows_read=20,
            source_columns=[c for c in BASELINE_HEADER if c != "dst_port"],
            report_key="quarantine/broken/missing-dst-port/report.md",
            draft_contract_key="quarantine/broken/missing-dst-port/draft-contract.yaml",
        ),
        None,
    )


def main() -> None:
    from app.config import get_settings

    settings = get_settings()
    if settings.app_env not in ("local", "test"):
        raise SystemExit(f"Refusing to seed APP_ENV={settings.app_env}: the fixture is for tests.")
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set.")
    engine = sa.create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            if conn.execute(sa.text("SELECT EXISTS (SELECT 1 FROM ingestion_runs)")).scalar():
                raise SystemExit("The database already holds ingestion runs; seed an empty one.")
        seed(engine)
    finally:
        engine.dispose()
    print("Seeded cse-cic-ids2018, simulated-real-traffic-01 and broken.")


if __name__ == "__main__":
    main()

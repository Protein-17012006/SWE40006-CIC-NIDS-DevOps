from datetime import date, datetime, timedelta

import pandas as pd
import pytest
import sqlalchemy as sa

from pipeline.accumulate import SAMPLE_COLUMNS, ColumnIssue
from pipeline.clean import STEPS
from pipeline.load import (
    FileData,
    RunRecord,
    dataset_summary,
    finish_run,
    latest_runs,
    mark_stale_runs,
    start_run,
    table_sizes,
)

pytestmark = pytest.mark.db
SAMPLE_ROWS = 3


def loaded_record(rows: int = 7, **overrides: object) -> RunRecord:
    values = {
        "status": "loaded",
        "message": f"Loaded {rows} of {rows} rows with cse-cic-ids2018 v1.",
        "contract_name": "cse-cic-ids2018",
        "contract_version": 1,
        "rows_read": rows,
        "rows_loaded": rows,
        "source_columns": ["Dst Port", "Label"],
        "first_ts": datetime(2018, 2, 14, 8, 0),
        "last_ts": datetime(2018, 2, 14, 10, 0),
    }
    values.update(overrides)
    return RunRecord(**values)


def file_data(flows: int = 7, extra_fields: tuple[str, ...] = ("fwd_pkt_len_max",)) -> FileData:
    hourly = pd.DataFrame(
        {
            "hour": [pd.Timestamp("2018-02-14 08:00"), pd.Timestamp("2018-02-14 09:00")],
            "label": ["Benign", "FTP-BruteForce"],
            "attack_category": ["Benign", "Brute force"],
            "flows": [flows - 2, 2],
        }
    )
    ports = pd.DataFrame(
        {
            "day": [date(2018, 2, 14), date(2018, 2, 14)],
            "attack_category": ["Benign", "Brute force"],
            "protocol": [6, 6],
            "dst_port": [443, 21],
            "flows": [flows - 2, 2],
        }
    )
    sample = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2018-02-14 08:31:01")] * SAMPLE_ROWS,
            "label": ["Benign"] * SAMPLE_ROWS,
            "attack_category": ["Benign"] * SAMPLE_ROWS,
            "dst_port": pd.array([443] * SAMPLE_ROWS, dtype="Int64"),
            "protocol": pd.array([6] * SAMPLE_ROWS, dtype="Int64"),
            "flow_duration_us": pd.array([1.5] * SAMPLE_ROWS, dtype="Float64"),
            "fwd_packets": pd.array([3] * SAMPLE_ROWS, dtype="Int64"),
            "bwd_packets": pd.array([1] * SAMPLE_ROWS, dtype="Int64"),
            "fwd_bytes": pd.array([10.0] * SAMPLE_ROWS, dtype="Float64"),
            "bwd_bytes": pd.array([0.0] * SAMPLE_ROWS, dtype="Float64"),
            "flow_bytes_per_s": pd.array([None] * SAMPLE_ROWS, dtype="Float64"),
            "flow_packets_per_s": pd.array([2.0] * SAMPLE_ROWS, dtype="Float64"),
            "src_ip": [None] * SAMPLE_ROWS,
            "dst_ip": [None] * SAMPLE_ROWS,
            "extras": [{"fwd_pkt_len_max": 3.0, "geo_country": None}] * SAMPLE_ROWS,
        }
    )
    assert list(sample.columns) == [*SAMPLE_COLUMNS, "extras"]
    return FileData(
        hourly=hourly,
        ports=ports,
        sample=sample,
        steps={step: 0 for step in STEPS} | {"duplicates_removed": 4},
        columns=[ColumnIssue("bwd_psh_flags", 0, 0, "constant, hidden")],
        fields=["timestamp", "dst_port", "label", "attack_category"],
        extra_fields=list(extra_fields),
        has_label=True,
    )


def load(engine, file_key="raw/d/a.csv", rows=7, record=None, data=None, dataset="d") -> int:
    run = start_run(engine, dataset, file_key, "abc1234")
    finish_run(engine, run, record or loaded_record(rows), data or file_data(rows))
    return run


def one(engine, query: str, **params: object):
    with engine.connect() as conn:
        return conn.execute(sa.text(query), params).mappings().one()


def count(engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


def dataset(engine, dataset_id: str):
    return one(engine, "SELECT * FROM datasets WHERE dataset_id = :d", d=dataset_id)


def run_row(engine, run_id: int):
    return one(engine, "SELECT * FROM ingestion_runs WHERE run_id = :r", r=run_id)


def test_start_run_records_a_running_run(engine):
    run = start_run(engine, "d", "raw/d/a.csv", "abc1234")
    row = run_row(engine, run)
    assert (row["status"], row["commit_sha"], row["file_key"]) == (
        "running",
        "abc1234",
        "raw/d/a.csv",
    )
    assert row["started_at"] is not None and row["ended_at"] is None


def test_finish_loaded_inserts_aggregates_and_dataset(engine):
    run = load(engine)
    ds = dataset(engine, "d")
    assert (ds["status"], ds["row_count"], ds["has_label"]) == ("loaded", 7, True)
    assert (ds["first_ts"], ds["last_ts"]) == (datetime(2018, 2, 14, 8), datetime(2018, 2, 14, 10))
    assert (ds["contract_name"], ds["contract_version"]) == ("cse-cic-ids2018", 1)
    assert ds["fields"] == ["timestamp", "dst_port", "label", "attack_category"]
    assert ds["extra_fields"] == ["fwd_pkt_len_max"] and ds["loaded_at"] is not None
    row = run_row(engine, run)
    assert (row["status"], row["rows_loaded"], row["ended_at"] is not None) == ("loaded", 7, True)
    assert row["source_columns"] == ["Dst Port", "Label"]
    assert row["first_ts"] == datetime(2018, 2, 14, 8)
    steps = one(
        engine,
        "SELECT rows_affected FROM quality_steps WHERE run_id = :r AND step = 'duplicates_removed'",
        r=run,
    )
    assert steps["rows_affected"] == 4 and count(engine, "quality_steps") == len(STEPS)
    issue = one(engine, "SELECT * FROM quality_columns WHERE run_id = :r", r=run)
    assert (issue["column_name"], issue["action"]) == ("bwd_psh_flags", "constant, hidden")
    assert (count(engine, "agg_ports"), count(engine, "flow_sample")) == (2, SAMPLE_ROWS)


def test_sample_extras_are_stored_as_jsonb(engine):
    load(engine)
    row = one(engine, "SELECT extras, flow_bytes_per_s, src_ip FROM flow_sample LIMIT 1")
    assert row["extras"] == {"fwd_pkt_len_max": 3.0, "geo_country": None}
    assert row["flow_bytes_per_s"] is None and row["src_ip"] is None


def test_loading_same_file_twice_replaces_rows(engine):
    load(engine)
    load(engine)
    assert dataset(engine, "d")["row_count"] == 7
    assert (count(engine, "flow_sample"), count(engine, "agg_hourly")) == (SAMPLE_ROWS, 2)
    assert count(engine, "ingestion_runs") == 2
    assert count(engine, "quality_steps") == 2 * len(STEPS)


def test_two_files_add_up(engine):
    load(engine, "raw/d/a.csv", rows=7)
    later = loaded_record(5, first_ts=datetime(2018, 2, 15, 1), last_ts=datetime(2018, 2, 15, 23))
    load(engine, "raw/d/b.csv", rows=5, record=later, data=file_data(5, ("pkt_entropy",)))
    ds = dataset(engine, "d")
    assert ds["row_count"] == 12
    assert (ds["first_ts"], ds["last_ts"]) == (datetime(2018, 2, 14, 8), datetime(2018, 2, 15, 23))
    assert ds["extra_fields"] == ["fwd_pkt_len_max", "pkt_entropy"]


def test_quarantine_keeps_an_earlier_load(engine):
    load(engine)
    run = start_run(engine, "d", "raw/d/a.csv", "def5678")
    finish_run(
        engine,
        run,
        RunRecord(
            status="quarantined",
            message="25.0% of rows failed validation with cse-cic-ids2018 v2.",
            contract_name="cse-cic-ids2018",
            contract_version=2,
            rows_read=8,
            rows_rejected=2,
            report_key="quarantine/d/a/report.md",
            draft_contract_key="quarantine/d/a/draft-contract.yaml",
        ),
    )
    ds = dataset(engine, "d")
    assert (ds["status"], ds["row_count"], ds["contract_version"]) == ("loaded", 7, 1)
    assert run_row(engine, run)["report_key"] == "quarantine/d/a/report.md"
    assert count(engine, "flow_sample") == SAMPLE_ROWS


def test_quarantine_of_a_new_dataset(engine):
    run = start_run(engine, "simulated-real-traffic-01", "raw/simulated-real-traffic-01.csv", "x")
    finish_run(
        engine,
        run,
        RunRecord(status="quarantined", message="No contract matches: missing dst_port."),
    )
    ds = dataset(engine, "simulated-real-traffic-01")
    assert (ds["status"], ds["contract_name"], ds["row_count"]) == ("quarantined", None, 0)
    assert (ds["display_name"], ds["has_label"], ds["fields"]) == (
        "simulated-real-traffic-01",
        False,
        [],
    )


def test_a_failed_run_touches_only_its_own_row(engine):
    run = start_run(engine, "d", "raw/d/a.csv", "abc1234")
    finish_run(engine, run, RunRecord(status="failed", message="Failed: OSError: disk full"))
    row = run_row(engine, run)
    assert (row["status"], row["message"]) == ("failed", "Failed: OSError: disk full")
    assert count(engine, "datasets") == 0


def test_latest_runs_one_per_file(engine):
    load(engine, "raw/d/a.csv")
    second = load(engine, "raw/d/a.csv")
    other = load(engine, "raw/d/b.csv")
    runs = {r.file_key: r for r in latest_runs(engine)}
    assert {k: r.run_id for k, r in runs.items()} == {"raw/d/a.csv": second, "raw/d/b.csv": other}
    assert runs["raw/d/a.csv"].source_columns == ["Dst Port", "Label"]
    assert (runs["raw/d/a.csv"].contract_name, runs["raw/d/a.csv"].contract_version) == (
        "cse-cic-ids2018",
        1,
    )


def test_stale_running_runs_become_failed(engine):
    stale = start_run(engine, "d", "raw/d/a.csv", "abc1234")
    fresh = start_run(engine, "d", "raw/d/b.csv", "abc1234")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE ingestion_runs SET started_at = now() - interval '3 hours' "
                "WHERE run_id = :r"
            ),
            {"r": stale},
        )
    assert mark_stale_runs(engine, older_than=timedelta(hours=2)) == 1
    assert run_row(engine, stale)["status"] == "failed"
    assert "stopped before" in run_row(engine, stale)["message"]
    assert run_row(engine, fresh)["status"] == "running"


def test_dataset_summary_and_table_sizes(engine):
    load(engine, "raw/d/a.csv")
    load(engine, "raw/d/b.csv")
    assert dataset_summary(engine) == [
        {
            "dataset_id": "d",
            "status": "loaded",
            "contract": "cse-cic-ids2018 v1",
            "row_count": 14,
            "files": 2,
        }
    ]
    sizes = table_sizes(engine)
    assert set(sizes) == {
        "datasets",
        "ingestion_runs",
        "quality_steps",
        "quality_columns",
        "agg_hourly",
        "agg_ports",
        "flow_sample",
    }
    assert all(size > 0 for size in sizes.values())

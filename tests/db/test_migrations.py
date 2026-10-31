import pytest
import sqlalchemy as sa

from pipeline.migrate import downgrade, upgrade

EXPECTED = {
    "datasets": {
        "dataset_id",
        "display_name",
        "contract_name",
        "contract_version",
        "status",
        "has_label",
        "fields",
        "extra_fields",
        "row_count",
        "first_ts",
        "last_ts",
        "loaded_at",
    },
    "ingestion_runs": {
        "run_id",
        "dataset_id",
        "file_key",
        "contract_name",
        "contract_version",
        "commit_sha",
        "started_at",
        "ended_at",
        "rows_read",
        "rows_loaded",
        "rows_rejected",
        "source_columns",
        "new_columns",
        "status",
        "report_key",
        "draft_contract_key",
        "message",
    },
    "quality_steps": {"run_id", "step", "rows_affected"},
    "quality_columns": {"run_id", "column_name", "nulls", "infinite", "action"},
    "agg_hourly": {"dataset_id", "file_key", "hour", "label", "attack_category", "flows"},
    "agg_ports": {
        "dataset_id",
        "file_key",
        "day",
        "attack_category",
        "protocol",
        "dst_port",
        "flows",
    },
    "flow_sample": {
        "sample_id",
        "dataset_id",
        "file_key",
        "ts",
        "label",
        "attack_category",
        "dst_port",
        "protocol",
        "flow_duration_us",
        "fwd_packets",
        "bwd_packets",
        "fwd_bytes",
        "bwd_bytes",
        "flow_bytes_per_s",
        "flow_packets_per_s",
        "src_ip",
        "dst_ip",
        "extras",
    },
}


def _table_columns(url: str) -> dict[str, set[str]]:
    engine = sa.create_engine(url)
    try:
        insp = sa.inspect(engine)
        return {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}
    finally:
        engine.dispose()


@pytest.mark.db
def test_upgrade_creates_the_seven_tables(migrated_db_url):
    tables = _table_columns(migrated_db_url)
    tables.pop("alembic_version", None)
    assert tables == EXPECTED


@pytest.mark.db
def test_run_status_is_constrained(migrated_db_url):
    engine = sa.create_engine(migrated_db_url)
    try:
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO ingestion_runs (dataset_id, file_key, commit_sha, status) "
                    "VALUES ('d', 'raw/f.csv', 'abc1234', 'done')"
                )
            )
    finally:
        engine.dispose()


@pytest.mark.db
def test_upgrade_twice_is_a_no_op(migrated_db_url):
    upgrade(migrated_db_url)
    assert set(_table_columns(migrated_db_url)) - {"alembic_version"} == set(EXPECTED)


@pytest.mark.db
def test_downgrade_removes_every_table(migrated_db_url):
    downgrade(migrated_db_url, "base")
    assert set(_table_columns(migrated_db_url)) <= {"alembic_version"}

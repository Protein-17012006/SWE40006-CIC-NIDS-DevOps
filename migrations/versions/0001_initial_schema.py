"""Initial schema: the seven tables the dashboard reads and the ingestion job fills.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT_ARRAY = postgresql.ARRAY(sa.Text())
EMPTY_ARRAY = sa.text("'{}'::text[]")


def _count(name: str) -> sa.Column:
    return sa.Column(name, sa.BigInteger(), nullable=False, server_default="0")


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("dataset_id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("contract_name", sa.Text()),
        sa.Column("contract_version", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("has_label", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fields", TEXT_ARRAY, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("extra_fields", TEXT_ARRAY, nullable=False, server_default=EMPTY_ARRAY),
        _count("row_count"),
        sa.Column("first_ts", sa.DateTime()),
        sa.Column("last_ts", sa.DateTime()),
        sa.Column("loaded_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('loaded', 'quarantined')", name="datasets_status_check"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("run_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("contract_name", sa.Text()),
        sa.Column("contract_version", sa.Integer()),
        sa.Column("commit_sha", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        _count("rows_read"),
        _count("rows_loaded"),
        _count("rows_rejected"),
        sa.Column("source_columns", TEXT_ARRAY, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("new_columns", TEXT_ARRAY, nullable=False, server_default=EMPTY_ARRAY),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("report_key", sa.Text()),
        sa.Column("draft_contract_key", sa.Text()),
        sa.Column("message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running', 'loaded', 'quarantined', 'failed')",
            name="ingestion_runs_status_check",
        ),
    )
    op.create_index(
        "ix_ingestion_runs_dataset_started", "ingestion_runs", ["dataset_id", "started_at"]
    )

    op.create_table(
        "quality_steps",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("ingestion_runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("step", sa.Text(), primary_key=True),
        sa.Column("rows_affected", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "quality_columns",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("ingestion_runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("column_name", sa.Text(), primary_key=True),
        _count("nulls"),
        _count("infinite"),
        sa.Column("action", sa.Text(), nullable=False),
    )

    op.create_table(
        "agg_hourly",
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("hour", sa.DateTime()),
        sa.Column("label", sa.Text()),
        sa.Column("attack_category", sa.Text()),
        sa.Column("flows", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_agg_hourly_dataset_hour", "agg_hourly", ["dataset_id", "hour"])
    op.create_index("ix_agg_hourly_dataset_file", "agg_hourly", ["dataset_id", "file_key"])

    op.create_table(
        "agg_ports",
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("day", sa.Date()),
        sa.Column("attack_category", sa.Text()),
        sa.Column("protocol", sa.Integer(), nullable=False),
        sa.Column("dst_port", sa.Integer(), nullable=False),
        sa.Column("flows", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_agg_ports_dataset_day", "agg_ports", ["dataset_id", "day"])
    op.create_index("ix_agg_ports_dataset_file", "agg_ports", ["dataset_id", "file_key"])

    op.create_table(
        "flow_sample",
        sa.Column("sample_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime()),
        sa.Column("label", sa.Text()),
        sa.Column("attack_category", sa.Text()),
        sa.Column("dst_port", sa.Integer(), nullable=False),
        sa.Column("protocol", sa.Integer(), nullable=False),
        sa.Column("flow_duration_us", sa.Double(), nullable=False),
        sa.Column("fwd_packets", sa.BigInteger(), nullable=False),
        sa.Column("bwd_packets", sa.BigInteger(), nullable=False),
        sa.Column("fwd_bytes", sa.Double(), nullable=False),
        sa.Column("bwd_bytes", sa.Double(), nullable=False),
        sa.Column("flow_bytes_per_s", sa.Double()),
        sa.Column("flow_packets_per_s", sa.Double()),
        sa.Column("src_ip", sa.Text()),
        sa.Column("dst_ip", sa.Text()),
        sa.Column(
            "extras", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.create_index(
        "ix_flow_sample_dataset_category", "flow_sample", ["dataset_id", "attack_category"]
    )
    op.create_index("ix_flow_sample_dataset_file", "flow_sample", ["dataset_id", "file_key"])


def downgrade() -> None:
    for table in (
        "flow_sample",
        "agg_ports",
        "agg_hourly",
        "quality_columns",
        "quality_steps",
        "ingestion_runs",
        "datasets",
    ):
        op.drop_table(table)

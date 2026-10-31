"""The first and last flow time of each run, so a dataset's time span spans its files.

Expand only: both columns are nullable, so an image older than this revision keeps working.

Revision ID: 0002_run_time_span
Revises: 0001_initial_schema
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_run_time_span"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_runs", sa.Column("first_ts", sa.DateTime()))
    op.add_column("ingestion_runs", sa.Column("last_ts", sa.DateTime()))


def downgrade() -> None:
    op.drop_column("ingestion_runs", "last_ts")
    op.drop_column("ingestion_runs", "first_ts")

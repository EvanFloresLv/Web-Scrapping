"""add metric_minute

Revision ID: 202610221600
Revises: 202610211000
Create Date: 2026-10-22 16:00:00

Spec 0012 (metrics & operational dashboard) AC-3. Pre aggregated minute
bucket table keyed by `(bucket_start, metric_name, labels)`. One row per
unique label combination per minute. Counters leave the `le_*` columns at
0; histograms populate all six finite bins (0.05/0.1/0.25/0.5/1/5 s).

The composite primary key uses `labels` (JSONB), which Postgres indexes
with hashing under the hood for equality lookups; the time range index
on `(bucket_start DESC)` serves the dashboard's "last hour" scans.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202610221600"
down_revision: str | None = "202610211000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metric_minute",
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "sum_value", sa.Float(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("le_50ms", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("le_100ms", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("le_250ms", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("le_500ms", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("le_1s", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("le_5s", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint(
            "bucket_start", "metric_name", "labels", name="pk_metric_minute"
        ),
    )
    op.create_index(
        "ix_metric_minute_bucket_start_desc",
        "metric_minute",
        [sa.text("bucket_start DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_metric_minute_bucket_start_desc", table_name="metric_minute")
    op.drop_table("metric_minute")

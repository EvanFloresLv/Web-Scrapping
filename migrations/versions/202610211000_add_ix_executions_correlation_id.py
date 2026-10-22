"""add ix_executions_correlation_id

Revision ID: 202610211000
Revises: 202610201200
Create Date: 2026-10-21 10:00:00

Spec 0010 (execution browser) AC-6. Adds a btree index on
`executions.correlation_id` so the support ticket lookup ("paste a
correlation id, land on the matching execution") is a point lookup, not
a seq scan.

The three existing indexes on `executions` (spec 0003 AC-14) all key on
`created_at` for the list sort; none cover `correlation_id`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "202610211000"
down_revision: str | None = "202610201200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_executions_correlation_id",
        "executions",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_executions_correlation_id",
        table_name="executions",
    )

"""add executions and execution_results

Revision ID: 202610201200
Revises: 202610200900
Create Date: 2026-10-20 12:00:00

Spec 0006 (workflow execution endpoint, sync), AC-15. Materialises the
`executions` and `execution_results` tables with every column, FK, CHECK, and
INDEX pinned by spec 0003 `## Feature design`. Parents (`workflow_versions`,
`target_urls`) already exist from features 4 and 5, so no DDL ordering trick
is needed. Downgrade drops `execution_results` first, then `executions`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202610201200"
down_revision: str | None = "202610200900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "executions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workflow_version_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "target_url_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "items_extracted",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="status_values",
        ),
        sa.CheckConstraint(
            "items_extracted >= 0",
            name="items_extracted_non_negative",
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 4000",
            name="error_message_length",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_versions.id"],
            name="fk_executions_workflow_version_id_workflow_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_url_id"],
            ["target_urls.id"],
            name="fk_executions_target_url_id_target_urls",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_executions"),
    )
    op.create_index(
        "ix_executions_workflow_version_id_created_at",
        "executions",
        ["workflow_version_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index(
        "ix_executions_target_url_id_created_at",
        "executions",
        ["target_url_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index(
        "ix_executions_status_created_at",
        "executions",
        ["status", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )

    op.create_table(
        "execution_results",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "execution_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("item_index >= 0", name="item_index_non_negative"),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
            name="fk_execution_results_execution_id_executions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_results"),
        sa.UniqueConstraint(
            "execution_id",
            "item_index",
            name="uq_execution_results_execution_id_item_index",
        ),
    )
    op.create_index(
        "ix_execution_results_execution_id",
        "execution_results",
        ["execution_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_results_execution_id",
        table_name="execution_results",
    )
    op.drop_table("execution_results")
    op.drop_index(
        "ix_executions_status_created_at",
        table_name="executions",
    )
    op.drop_index(
        "ix_executions_target_url_id_created_at",
        table_name="executions",
    )
    op.drop_index(
        "ix_executions_workflow_version_id_created_at",
        table_name="executions",
    )
    op.drop_table("executions")

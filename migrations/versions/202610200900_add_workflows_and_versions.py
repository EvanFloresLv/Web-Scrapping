"""add scraping_workflows and workflow_versions

Revision ID: 202610200900
Revises: 202610191000
Create Date: 2026-10-20 09:00:00

Spec 0004 (workflow configuration & versioning), AC-14. Creates both tables
with the two-step cycle break: `scraping_workflows` is created without the
`current_version_id` FK, `workflow_versions` is created next, then the FK is
added via ALTER TABLE. Downgrade removes the FK first, then both tables in
reverse order.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202610200900"
down_revision: str | None = "202610191000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scraping_workflows",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("website_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "current_version_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 200",
            name="name_length",
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 2000",
            name="description_length",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="status_values",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_scraping_workflows_website_id_websites",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scraping_workflows"),
    )
    op.create_index(
        "ix_scraping_workflows_website_id",
        "scraping_workflows",
        ["website_id"],
    )
    op.create_index(
        "uq_scraping_workflows_website_id_name_active",
        "scraping_workflows",
        ["website_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("config", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("version_number >= 1", name="version_number_positive"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="status_values",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["scraping_workflows.id"],
            name="fk_workflow_versions_workflow_id_scraping_workflows",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_versions"),
        sa.UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_workflow_versions_workflow_id_version_number",
        ),
    )
    op.create_index(
        "ix_workflow_versions_workflow_id",
        "workflow_versions",
        ["workflow_id"],
    )
    op.create_index(
        "ix_workflow_versions_workflow_id_status",
        "workflow_versions",
        ["workflow_id", "status"],
    )

    op.create_foreign_key(
        "fk_scraping_workflows_current_version_id_workflow_versions",
        "scraping_workflows",
        "workflow_versions",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_scraping_workflows_current_version_id_workflow_versions",
        "scraping_workflows",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_workflow_versions_workflow_id_status",
        table_name="workflow_versions",
    )
    op.drop_index("ix_workflow_versions_workflow_id", table_name="workflow_versions")
    op.drop_table("workflow_versions")
    op.drop_index(
        "uq_scraping_workflows_website_id_name_active",
        table_name="scraping_workflows",
    )
    op.drop_index(
        "ix_scraping_workflows_website_id",
        table_name="scraping_workflows",
    )
    op.drop_table("scraping_workflows")

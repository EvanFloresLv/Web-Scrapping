"""add websites and target_urls

Revision ID: 202610191000
Revises:
Create Date: 2026-10-19 10:00:00

Spec 0002 (website & target registration). Creates the two tables, both
partial unique indexes (dedup + re-registration-after-soft-delete), the FK
index on `target_urls.website_id`, CHECK constraints on `status`, and length
checks on text columns. Satisfies AC-1, AC-2, AC-4, AC-7, AC-11, AC-12.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202610191000"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "websites",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
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
            "char_length(host) BETWEEN 1 AND 253",
            name="host_length",
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 200",
            name="display_name_length",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="status_values",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_websites"),
    )
    op.create_index(
        "uq_websites_host_active",
        "websites",
        ["host"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "target_urls",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("website_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
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
            "char_length(url) BETWEEN 1 AND 2048",
            name="url_length",
        ),
        sa.CheckConstraint(
            "char_length(label) BETWEEN 1 AND 200",
            name="label_length",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="status_values",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name="fk_target_urls_website_id_websites",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_target_urls"),
    )
    op.create_index(
        "ix_target_urls_website_id",
        "target_urls",
        ["website_id"],
    )
    op.create_index(
        "uq_target_urls_website_id_url_active",
        "target_urls",
        ["website_id", "url"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_target_urls_website_id_url_active", table_name="target_urls")
    op.drop_index("ix_target_urls_website_id", table_name="target_urls")
    op.drop_table("target_urls")
    op.drop_index("uq_websites_host_active", table_name="websites")
    op.drop_table("websites")

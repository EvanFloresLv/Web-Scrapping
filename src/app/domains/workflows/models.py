"""SQLAlchemy ORM models for the workflows domain (spec 0003).

Defines `ScrapingWorkflow` and `WorkflowVersion` with every column, CHECK
constraint, FK, and index pinned by spec 0003's `## Feature design` tables.
Registered with the project's declarative `Base` so Alembic autogenerate can
see them. The migration itself ships with feature 5 (per AC-15); this file is
the shape every migration conforms to.

FK ordering note (spec 0003 Follow-up): the two tables form a cycle via
`scraping_workflows.current_version_id -> workflow_versions.id`. Feature 5's
migration must create `scraping_workflows` without that FK, create
`workflow_versions`, then `ALTER TABLE ... ADD CONSTRAINT fk_current_version
...`. SQLAlchemy's `use_alter=True` on the FK below gives Alembic the hint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.ids import uuid_v7
from app.domains.workflows.enums import WorkflowStatus, WorkflowVersionStatus


class ScrapingWorkflow(Base):
    """Mutable aggregate root for a scraping workflow (AC-2).

    One row per workflow. A workflow belongs to exactly one website (AC-3) and
    points at the currently published version via `current_version_id` (AC-4,
    nullable until the first publish). Soft deleted via `deleted_at` (AC-9).
    """

    __tablename__ = "scraping_workflows"
    __table_args__ = (
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 200",
            name="name_length",
        ),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 2000",
            name="description_length",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="status_values",
        ),
        Index(
            "uq_scraping_workflows_website_id_name_active",
            "website_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_scraping_workflows_website_id", "website_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_v7)
    website_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("websites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "workflow_versions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_scraping_workflows_current_version_id_workflow_versions",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=WorkflowStatus.ACTIVE.value,
        server_default=WorkflowStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list[WorkflowVersion]] = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        foreign_keys="WorkflowVersion.workflow_id",
        cascade="save-update",
        lazy="raise_on_sql",
    )


class WorkflowVersion(Base):
    """Immutable child of `ScrapingWorkflow` (AC-2).

    A version holds one atomic `WorkflowConfig` JSONB document (AC-5). A row is
    editable only while `status='draft'`; once published the content columns
    (`workflow_id`, `version_number`, `config`) are write once (AC-13). The
    allowed state flow is `draft -> published -> archived` (AC-12).
    """

    __tablename__ = "workflow_versions"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="status_values",
        ),
        UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_workflow_versions_workflow_id_version_number",
        ),
        Index("ix_workflow_versions_workflow_id_status", "workflow_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_v7)
    workflow_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("scraping_workflows.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=WorkflowVersionStatus.DRAFT.value,
        server_default=WorkflowVersionStatus.DRAFT.value,
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    workflow: Mapped[ScrapingWorkflow] = relationship(
        "ScrapingWorkflow",
        back_populates="versions",
        foreign_keys=[workflow_id],
        lazy="raise_on_sql",
    )

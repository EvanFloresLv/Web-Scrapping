"""SQLAlchemy ORM models for the executions domain (spec 0003).

Defines `Execution` and `ExecutionResult`. Both are append only records
(AC-7, AC-9): no soft delete column, no update after terminal (enforced at the
service layer). Cross domain FKs point at `workflow_versions.id` and
`target_urls.id` by string table name; no Python level import of the other
domains' models, which would cross the `app.domains.*` independence boundary
pinned by `import-linter` in `pyproject.toml`.

Each slice feature ships its own migration (per AC-15); feature 7 owns the one
that creates these two tables.
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.ids import uuid_v7
from app.domains.executions.enums import ExecutionStatus


class Execution(Base):
    """One execution attempt (AC-6).

    Persisted whether the run succeeds or fails, so the execution browser
    (feature 11) lists both the same way. `correlation_id` is sourced from the
    `asgi-correlation-id` middleware when the run starts inside an HTTP
    request; outside a request (feature 23's async worker, cron hooks) the
    executor mints a fresh UUIDv7 and binds it to the structlog contextvar
    before the insert, so the column is always NOT NULL.
    """

    __tablename__ = "executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="status_values",
        ),
        CheckConstraint("items_extracted >= 0", name="items_extracted_non_negative"),
        CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 4000",
            name="error_message_length",
        ),
        Index(
            "ix_executions_workflow_version_id_created_at",
            "workflow_version_id",
            "created_at",
            postgresql_ops={"created_at": "DESC"},
        ),
        Index(
            "ix_executions_target_url_id_created_at",
            "target_url_id",
            "created_at",
            postgresql_ops={"created_at": "DESC"},
        ),
        Index(
            "ix_executions_status_created_at",
            "status",
            "created_at",
            postgresql_ops={"created_at": "DESC"},
        ),
        # Spec 0010 AC-6: support ticket lookup "paste the correlation id,
        # land on the matching execution" without a seq scan.
        Index(
            "ix_executions_correlation_id",
            "correlation_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_v7)
    workflow_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_url_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("target_urls.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ExecutionStatus.PENDING.value,
        server_default=ExecutionStatus.PENDING.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_extracted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(Text, nullable=False)
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

    results: Mapped[list[ExecutionResult]] = relationship(
        "ExecutionResult",
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise_on_sql",
    )


class ExecutionResult(Base):
    """One extracted item from an `Execution` (AC-7).

    Append only; the row is immutable after insert (AC-13). Deleted only via
    DB CASCADE when the parent `Execution` is hard deleted by a future
    retention job (AC-10).
    """

    __tablename__ = "execution_results"
    __table_args__ = (
        CheckConstraint("item_index >= 0", name="item_index_non_negative"),
        UniqueConstraint(
            "execution_id",
            "item_index",
            name="uq_execution_results_execution_id_item_index",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_v7)
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    execution: Mapped[Execution] = relationship(
        "Execution",
        back_populates="results",
        lazy="raise_on_sql",
    )

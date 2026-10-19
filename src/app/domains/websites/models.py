"""SQLAlchemy ORM models for the websites domain (spec 0002).

Defines `Website` and `TargetURL` with every column, CHECK constraint, FK,
and index pinned by spec 0002's `## Feature design` tables. Registered with
the shared declarative `Base` so Alembic autogenerate can see them.

Soft delete lives on `deleted_at` (nullable `TIMESTAMPTZ`). The partial
unique indexes (`WHERE deleted_at IS NULL`) let the same host (resp.
`(website_id, url)`) be re-registered after a delete, per AC-12.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.ids import uuid_v7
from app.domains.websites.enums import TargetStatus, WebsiteStatus


class Website(Base):
    """Mutable aggregate root for a registered website (spec 0002, AC-1).

    One row per canonical host. Soft deleted via `deleted_at`; after delete
    the same host can be registered again (AC-12) because the uniqueness
    constraint is partial on `deleted_at IS NULL`.
    """

    __tablename__ = "websites"
    __table_args__ = (
        CheckConstraint(
            "char_length(host) BETWEEN 1 AND 253",
            name="host_length",
        ),
        CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 200",
            name="display_name_length",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="status_values",
        ),
        Index(
            "uq_websites_host_active",
            "host",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_v7)
    host: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=WebsiteStatus.ACTIVE.value,
        server_default=WebsiteStatus.ACTIVE.value,
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

    targets: Mapped[list[TargetURL]] = relationship(
        "TargetURL",
        back_populates="website",
        cascade="save-update",
        lazy="raise_on_sql",
    )


class TargetURL(Base):
    """A concrete URL nested under one `Website` (spec 0002, AC-2).

    The URL is stored in canonical form; its host must equal the parent
    website's host (AC-5, enforced in the service layer). Soft deleted via
    `deleted_at`; cascade soft delete is driven by `WebsiteService` in the
    same transaction (AC-11).
    """

    __tablename__ = "target_urls"
    __table_args__ = (
        CheckConstraint(
            "char_length(url) BETWEEN 1 AND 2048",
            name="url_length",
        ),
        CheckConstraint(
            "char_length(label) BETWEEN 1 AND 200",
            name="label_length",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="status_values",
        ),
        Index(
            "uq_target_urls_website_id_url_active",
            "website_id",
            "url",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_target_urls_website_id", "website_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid_v7)
    website_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("websites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=TargetStatus.ACTIVE.value,
        server_default=TargetStatus.ACTIVE.value,
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

    website: Mapped[Website] = relationship(
        "Website",
        back_populates="targets",
        lazy="raise_on_sql",
    )

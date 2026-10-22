"""ORM model for the pre aggregated minute bucket table.

Spec 0012 AC-3. One row per `(bucket_start, metric_name, labels)` triple.
Counters leave the `le_*` columns at 0; histograms populate all of them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, Index, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MetricMinute(Base):
    """Pre aggregated minute bucket of observations for one metric + label set."""

    __tablename__ = "metric_minute"

    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    labels: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    sum_value: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    le_50ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    le_100ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    le_250ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    le_500ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    le_1s: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    le_5s: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    __table_args__ = (
        PrimaryKeyConstraint(
            "bucket_start",
            "metric_name",
            "labels",
            name="pk_metric_minute",
        ),
        Index(
            "ix_metric_minute_bucket_start_desc",
            "bucket_start",
            postgresql_using="btree",
            postgresql_ops={"bucket_start": "DESC"},
        ),
    )

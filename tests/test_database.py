"""Database wiring: naming convention pin, Base, and the ping helper.

The engine/session factory are process globals; we only check that the shape
matches spec 0001 and that `ping` round-trips a SELECT 1. We do not open a real
connection here (Postgres fixture lands in Feature 3).
"""

from __future__ import annotations

import pytest

from app.core.database import NAMING_CONVENTION, Base, metadata, ping


def test_naming_convention_matches_spec_pins() -> None:
    """Alembic autogenerate diffs stay stable only if these keys are frozen."""
    assert NAMING_CONVENTION == {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }


def test_declarative_base_uses_shared_metadata() -> None:
    assert Base.metadata is metadata
    assert metadata.naming_convention == NAMING_CONVENTION


class _OneSession:
    """Minimal async session whose execute returns scalar_one()==1."""

    async def execute(self, _stmt):  # type: ignore[no-untyped-def]
        class _Result:
            def scalar_one(self) -> int:
                return 1

        return _Result()


class _ZeroSession:
    async def execute(self, _stmt):  # type: ignore[no-untyped-def]
        class _Result:
            def scalar_one(self) -> int:
                return 0

        return _Result()


@pytest.mark.asyncio
async def test_ping_returns_true_when_select_one_matches() -> None:
    assert await ping(_OneSession()) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ping_returns_false_when_select_one_does_not_match() -> None:
    assert await ping(_ZeroSession()) is False  # type: ignore[arg-type]

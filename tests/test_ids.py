"""Covers `app.core.ids.uuid_v7` (spec 0003, AC-8).

Every PK on the four MVP tables defaults to `uuid_v7()`; this file locks in the
one invariant the ORM defaults rely on: the helper returns time ordered UUIDv7
values typed as the stdlib `uuid.UUID` class.
"""

from __future__ import annotations

import time
from uuid import UUID

from app.core.ids import uuid_v7


def test_returns_stdlib_uuid_class() -> None:
    # covers: AC-8
    assert type(uuid_v7()) is UUID


def test_returns_version_7() -> None:
    # covers: AC-8
    assert uuid_v7().version == 7


def test_values_are_unique_across_calls() -> None:
    # covers: AC-8
    values = {uuid_v7() for _ in range(1000)}
    assert len(values) == 1000


def test_values_are_time_ordered() -> None:
    # covers: AC-8 (time ordering is the one property worth paying for; cursors depend on it)
    first = uuid_v7()
    time.sleep(0.002)  # UUIDv7 ms precision; ensure the second value lands in a later ms
    second = uuid_v7()
    assert first < second

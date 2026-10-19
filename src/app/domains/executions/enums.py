"""Lifecycle enum for the executions domain (spec 0003, AC-12).

Mirrored by the DB CHECK constraint on `executions.status`. Terminal states
(`COMPLETED`, `FAILED`) are immutable at the service layer (AC-13).
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionStatus(StrEnum):
    """`executions.status` values. Flow: pending -> running -> completed | failed.

    `pending -> failed` is also valid (validation reject before start, AC-12).
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @classmethod
    def terminal(cls) -> frozenset[ExecutionStatus]:
        """Return the terminal states (immutable rows past this point)."""
        return frozenset({cls.COMPLETED, cls.FAILED})

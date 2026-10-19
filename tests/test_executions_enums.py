"""Covers `app.domains.executions.enums` (spec 0003, AC-12).

Locks the four allowed `executions.status` values and the `terminal()` set the
service layer uses to decide whether a row is still mutable.
"""

from __future__ import annotations

from enum import StrEnum

from app.domains.executions.enums import ExecutionStatus


def test_values_match_check_literals() -> None:
    # covers: AC-12
    assert {s.value for s in ExecutionStatus} == {"pending", "running", "completed", "failed"}


def test_is_str_enum() -> None:
    assert issubclass(ExecutionStatus, StrEnum)


def test_terminal_set() -> None:
    # covers: AC-12, AC-13 (terminal rows are immutable past this set)
    assert ExecutionStatus.terminal() == frozenset(
        {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED}
    )


def test_terminal_is_frozen() -> None:
    # covers: AC-12 (callers must not be able to mutate the terminal set)
    terminal = ExecutionStatus.terminal()
    assert isinstance(terminal, frozenset)
    assert ExecutionStatus.PENDING not in terminal
    assert ExecutionStatus.RUNNING not in terminal

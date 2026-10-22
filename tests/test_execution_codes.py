"""Covers `app.core.errors.execution_codes` (spec 0003, AC-17).

This slice ships empty prefix shells; feature 6, 7, 15, and 17 extend their own.
The lock is that the four prefixes exist, each as a `StrEnum`, and that they
compose into a single union type the writer side can reference.
"""

from __future__ import annotations

from enum import StrEnum
from typing import get_args

from app.core.errors import execution_codes as reg


def test_four_prefix_shells_exposed() -> None:
    # covers: AC-17
    for name in ("FetchErrorCode", "ExtractionErrorCode", "ExecutionErrorCode", "AgentErrorCode"):
        assert hasattr(reg, name), f"missing error-code shell: {name}"


def test_each_prefix_is_a_str_enum() -> None:
    # covers: AC-17
    for cls in (
        reg.FetchErrorCode,
        reg.ExtractionErrorCode,
        reg.ExecutionErrorCode,
        reg.AgentErrorCode,
    ):
        assert issubclass(cls, StrEnum), f"{cls.__name__} must be a StrEnum"


def test_agent_shell_stays_empty_until_its_slice() -> None:
    # covers: AC-17 (feature 6 populates fetch.* and extraction.*; feature 7
    # populates execution.*; feature 15+ populate agent.*)
    assert (
        len(list(reg.AgentErrorCode)) == 0
    ), f"AgentErrorCode should still be empty; got {list(reg.AgentErrorCode)}"


def test_feature_7_execution_codes_present() -> None:
    # covers: spec 0006 AC-10 (feature 7 populates execution.*),
    # spec 0010 AC-2/AC-3 (feature 11 extends with the list endpoint codes).
    expected = {
        "execution.workflow_not_runnable",
        "execution.version_not_published",
        "execution.version_archived",
        "execution.target_not_registered",
        "execution.invalid_execute_body",
        "execution.terminal_persist_failed",
        "execution.not_found",
        "execution.invalid_cursor",
        "execution.invalid_list_query",
    }
    assert {c.value for c in reg.ExecutionErrorCode} == expected
    for code in reg.ExecutionErrorCode:
        assert code.value.startswith("execution.")


def test_feature_6_codes_present() -> None:
    # covers: spec 0005 AC-14 (feature 6 extends FetchErrorCode + ExtractionErrorCode)
    assert reg.FetchErrorCode.TIMEOUT == "fetch.timeout"
    assert reg.ExtractionErrorCode.NO_CONTAINER_MATCH == "extraction.no_container_match"


def test_value_union_composes_all_four_prefixes() -> None:
    # covers: AC-17 (one union, one import for writer type hints once codes land)
    assert set(get_args(reg.ExecutionErrorCodeValue)) == {
        reg.FetchErrorCode,
        reg.ExtractionErrorCode,
        reg.ExecutionErrorCode,
        reg.AgentErrorCode,
    }


def test_module_all_lists_the_public_surface() -> None:
    assert set(reg.__all__) == {
        "AgentErrorCode",
        "ExecutionErrorCode",
        "ExecutionErrorCodeValue",
        "ExtractionErrorCode",
        "FetchErrorCode",
        "WorkflowErrorCode",
    }

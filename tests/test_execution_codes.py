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


def test_shells_are_empty_for_this_slice() -> None:
    # covers: AC-17 (concrete codes land with feature 6/7/15/17)
    for cls in (
        reg.FetchErrorCode,
        reg.ExtractionErrorCode,
        reg.ExecutionErrorCode,
        reg.AgentErrorCode,
    ):
        assert len(list(cls)) == 0, f"{cls.__name__} should ship empty; got {list(cls)}"


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
    }

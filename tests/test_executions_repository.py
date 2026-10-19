"""Covers `app.domains.executions.repository` (spec 0003, AC-6, AC-20).

The three list-by methods back the three composite indexes on `executions`;
their keyword-only `with_deleted=False` is the uniform history opt-in.
"""

from __future__ import annotations

from inspect import Parameter, signature
from typing import Protocol

from app.domains.executions.repository import ExecutionRepository, ExecutionResultRepository

READ_METHODS = {
    "get",
    "list_for_workflow_version",
    "list_for_target_url",
    "list_by_status",
    "list_for_execution",
}


def test_both_protocols_are_runtime_protocols() -> None:
    # covers: AC-6
    assert issubclass(ExecutionRepository, Protocol)  # type: ignore[arg-type]
    assert issubclass(ExecutionResultRepository, Protocol)  # type: ignore[arg-type]


def test_execution_repository_lists_the_expected_methods() -> None:
    # covers: AC-6
    names = {
        n
        for n in vars(ExecutionRepository)
        if not n.startswith("_") and callable(vars(ExecutionRepository)[n])
    }
    assert {
        "get",
        "list_for_workflow_version",
        "list_for_target_url",
        "list_by_status",
        "add",
        "finalise",
    } <= names


def test_execution_result_repository_lists_the_expected_methods() -> None:
    # covers: AC-7
    names = {
        n
        for n in vars(ExecutionResultRepository)
        if not n.startswith("_") and callable(vars(ExecutionResultRepository)[n])
    }
    assert {"list_for_execution", "add_many"} <= names


def test_execution_repository_read_methods_have_with_deleted_kw_only() -> None:
    # covers: AC-20
    for name in ("get", "list_for_workflow_version", "list_for_target_url", "list_by_status"):
        sig = signature(getattr(ExecutionRepository, name))
        wd = sig.parameters.get("with_deleted")
        assert wd is not None, f"{name} is missing with_deleted"
        assert wd.kind is Parameter.KEYWORD_ONLY, f"{name}.with_deleted must be keyword-only"
        assert wd.default is False
        assert wd.annotation in (bool, "bool")


def test_execution_result_repository_read_methods_have_with_deleted_kw_only() -> None:
    # covers: AC-20
    sig = signature(ExecutionResultRepository.list_for_execution)
    wd = sig.parameters.get("with_deleted")
    assert wd is not None
    assert wd.kind is Parameter.KEYWORD_ONLY
    assert wd.default is False
    assert wd.annotation in (bool, "bool")


def test_mutation_methods_do_not_expose_with_deleted() -> None:
    # covers: AC-20
    for cls, methods in (
        (ExecutionRepository, ("add", "finalise")),
        (ExecutionResultRepository, ("add_many",)),
    ):
        for name in methods:
            sig = signature(getattr(cls, name))
            assert (
                "with_deleted" not in sig.parameters
            ), f"{cls.__name__}.{name} must not take with_deleted"

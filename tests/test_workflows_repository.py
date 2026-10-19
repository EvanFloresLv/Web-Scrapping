"""Covers `app.domains.workflows.repository` (spec 0003, AC-2, AC-20).

Both protocols must expose `with_deleted: bool = False` as a keyword-only
parameter on every read method, so the opt-in to history reads is uniform
across the codebase. Concrete implementations land with feature 5.
"""

from __future__ import annotations

from inspect import Parameter, signature
from typing import Protocol

from app.domains.workflows.repository import WorkflowRepository, WorkflowVersionRepository

READ_METHODS = {"get", "list_for_website", "list_for_workflow"}


def _read_method_names(cls: type) -> list[str]:
    return [n for n in vars(cls) if n in READ_METHODS and not n.startswith("_")]


def test_both_protocols_are_runtime_protocols() -> None:
    # covers: AC-2 (persistence surface is a Protocol, not a concrete class in this slice)
    assert issubclass(WorkflowRepository, Protocol)  # type: ignore[arg-type]
    assert issubclass(WorkflowVersionRepository, Protocol)  # type: ignore[arg-type]


def test_workflow_repository_lists_the_expected_methods() -> None:
    # covers: AC-2 (surface shape)
    names = {
        n
        for n in vars(WorkflowRepository)
        if not n.startswith("_") and callable(vars(WorkflowRepository)[n])
    }
    assert {"get", "list_for_website", "add", "soft_delete", "set_current_version"} <= names


def test_workflow_version_repository_lists_the_expected_methods() -> None:
    # covers: AC-2
    names = {
        n
        for n in vars(WorkflowVersionRepository)
        if not n.startswith("_") and callable(vars(WorkflowVersionRepository)[n])
    }
    assert {"get", "list_for_workflow", "add_draft", "update_draft", "publish", "archive"} <= names


def test_workflow_repository_read_methods_have_with_deleted_kw_only() -> None:
    # covers: AC-20
    for name in _read_method_names(WorkflowRepository):
        sig = signature(getattr(WorkflowRepository, name))
        wd = sig.parameters.get("with_deleted")
        assert wd is not None, f"{name} is missing with_deleted"
        assert wd.kind is Parameter.KEYWORD_ONLY, f"{name}.with_deleted must be keyword-only"
        assert wd.default is False, f"{name}.with_deleted default must be False"
        assert wd.annotation in (bool, "bool"), f"{name}.with_deleted must be typed as bool"


def test_workflow_version_repository_read_methods_have_with_deleted_kw_only() -> None:
    # covers: AC-20
    read_names = {"get", "list_for_workflow"}
    for name in read_names:
        sig = signature(getattr(WorkflowVersionRepository, name))
        wd = sig.parameters.get("with_deleted")
        assert wd is not None, f"{name} is missing with_deleted"
        assert wd.kind is Parameter.KEYWORD_ONLY
        assert wd.default is False
        assert wd.annotation in (bool, "bool")


def test_mutation_methods_do_not_expose_with_deleted() -> None:
    # covers: AC-20 (with_deleted only steers reads; writes do not take it)
    for cls, methods in (
        (WorkflowRepository, ("add", "soft_delete", "set_current_version")),
        (WorkflowVersionRepository, ("add_draft", "update_draft", "publish", "archive")),
    ):
        for name in methods:
            sig = signature(getattr(cls, name))
            assert (
                "with_deleted" not in sig.parameters
            ), f"{cls.__name__}.{name} must not take with_deleted"

"""Covers `app.domains.workflows.enums` (spec 0003, AC-12).

Enum string values must match the DB `CHECK` constraint literals on
`scraping_workflows.status` and `workflow_versions.status`; a drift here
produces inserts that pass Python but fail Postgres.
"""

from __future__ import annotations

from enum import StrEnum

from app.domains.workflows.enums import WorkflowStatus, WorkflowVersionStatus


def test_workflow_status_values_match_check_literals() -> None:
    # covers: AC-12 (scraping_workflows.status IN ('active','inactive'))
    assert {s.value for s in WorkflowStatus} == {"active", "inactive"}


def test_workflow_status_is_str_enum() -> None:
    assert issubclass(WorkflowStatus, StrEnum)


def test_workflow_version_status_values_match_check_literals() -> None:
    # covers: AC-12 (workflow_versions.status IN ('draft','published','archived'))
    assert {s.value for s in WorkflowVersionStatus} == {"draft", "published", "archived"}


def test_workflow_version_status_is_str_enum() -> None:
    assert issubclass(WorkflowVersionStatus, StrEnum)

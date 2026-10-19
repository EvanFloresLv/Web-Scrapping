"""Covers `app.domains.workflows.config` (spec 0003, AC-5, AC-13).

`WorkflowConfig` is the one validator every write to `workflow_versions.config`
passes through. These tests pin: the four required pins (`container_selector`,
`fields`, `output_schema`, optional `pagination`), additive forward compat via
`extra='allow'`, nested model shapes, and the error cases that must surface as
Pydantic validation failures (which the API handler maps to Problem Details).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.domains.workflows.config import FieldSpec, PaginationSpec, WorkflowConfig


def _good_payload() -> dict[str, Any]:
    return {
        "container_selector": ".product",
        "fields": [
            {"name": "title", "selector": ".title", "transforms": ["strip"], "type": "str"},
        ],
        "output_schema": {"title": "string"},
    }


def test_validates_minimal_good_payload() -> None:
    # covers: AC-5 (happy path)
    cfg = WorkflowConfig.model_validate(_good_payload())
    assert cfg.container_selector == ".product"
    assert len(cfg.fields) == 1
    assert cfg.fields[0].name == "title"
    assert cfg.pagination is None


def test_rejects_missing_container_selector() -> None:
    # covers: AC-5 (422 path: a payload missing a required pin is never written)
    payload = _good_payload()
    del payload["container_selector"]
    with pytest.raises(ValidationError) as info:
        WorkflowConfig.model_validate(payload)
    assert "container_selector" in str(info.value)


def test_rejects_empty_container_selector() -> None:
    # covers: AC-5 (an empty string selector cannot locate anything; fail fast at write)
    payload = _good_payload()
    payload["container_selector"] = ""
    with pytest.raises(ValidationError):
        WorkflowConfig.model_validate(payload)


def test_rejects_missing_fields() -> None:
    # covers: AC-5
    payload = _good_payload()
    del payload["fields"]
    with pytest.raises(ValidationError):
        WorkflowConfig.model_validate(payload)


def test_rejects_empty_fields_list() -> None:
    # covers: AC-5 (a workflow with no fields extracts nothing; reject at write)
    payload = _good_payload()
    payload["fields"] = []
    with pytest.raises(ValidationError):
        WorkflowConfig.model_validate(payload)


def test_rejects_missing_output_schema() -> None:
    # covers: AC-5
    payload = _good_payload()
    del payload["output_schema"]
    with pytest.raises(ValidationError):
        WorkflowConfig.model_validate(payload)


def test_pagination_is_optional() -> None:
    # covers: AC-5 (pagination may be omitted entirely)
    cfg = WorkflowConfig.model_validate(_good_payload())
    assert cfg.pagination is None


def test_pagination_parses_when_present() -> None:
    # covers: AC-5
    payload = _good_payload()
    payload["pagination"] = {"next_selector": ".next", "max_pages": 10}
    cfg = WorkflowConfig.model_validate(payload)
    assert cfg.pagination is not None
    assert cfg.pagination.next_selector == ".next"
    assert cfg.pagination.max_pages == 10


def test_pagination_rejects_zero_max_pages() -> None:
    # covers: AC-5 (max_pages must be >= 1 to be a meaningful bound)
    payload = _good_payload()
    payload["pagination"] = {"next_selector": ".next", "max_pages": 0}
    with pytest.raises(ValidationError):
        WorkflowConfig.model_validate(payload)


def test_extra_allow_keeps_unknown_top_level_keys() -> None:
    # covers: AC-5 (forward compat: a new optional field in a later spec revision
    # must not break historical row reads)
    payload = _good_payload()
    payload["future_optional_field"] = {"anything": 1}
    cfg = WorkflowConfig.model_validate(payload)
    dumped = cfg.model_dump()
    assert dumped["future_optional_field"] == {"anything": 1}


def test_extra_allow_on_field_spec() -> None:
    # covers: AC-5 (same forward-compat guarantee inside field entries)
    payload = _good_payload()
    payload["fields"][0]["provider_hint"] = "css"
    cfg = WorkflowConfig.model_validate(payload)
    assert cfg.fields[0].model_dump()["provider_hint"] == "css"


def test_extra_allow_on_pagination_spec() -> None:
    # covers: AC-5
    payload = _good_payload()
    payload["pagination"] = {"next_selector": ".next", "max_pages": 3, "respect_rel_next": True}
    cfg = WorkflowConfig.model_validate(payload)
    assert cfg.pagination is not None
    assert cfg.pagination.model_dump()["respect_rel_next"] is True


def test_field_spec_defaults_transforms_to_empty_list() -> None:
    # covers: AC-5 (transforms is optional; absence means no transform chain)
    spec = FieldSpec.model_validate({"name": "title", "selector": ".title", "type": "str"})
    assert spec.transforms == []


def test_field_spec_rejects_empty_name() -> None:
    # covers: AC-5
    with pytest.raises(ValidationError):
        FieldSpec.model_validate({"name": "", "selector": ".title", "type": "str"})


def test_field_spec_rejects_empty_selector() -> None:
    # covers: AC-5
    with pytest.raises(ValidationError):
        FieldSpec.model_validate({"name": "title", "selector": "", "type": "str"})


def test_field_spec_rejects_missing_type() -> None:
    # covers: AC-5
    with pytest.raises(ValidationError):
        FieldSpec.model_validate({"name": "title", "selector": ".title"})


def test_pagination_spec_rejects_empty_next_selector() -> None:
    with pytest.raises(ValidationError):
        PaginationSpec.model_validate({"next_selector": "", "max_pages": 5})


def test_round_trips_through_model_dump_and_validate() -> None:
    # covers: AC-5, AC-13 (what the service persists must re-load bit for bit)
    cfg = WorkflowConfig.model_validate(_good_payload())
    reload = WorkflowConfig.model_validate(cfg.model_dump())
    assert reload.model_dump() == cfg.model_dump()

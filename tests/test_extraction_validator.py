"""Unit tests for `OutputSchemaValidator` (spec 0005 AC-11).

Draft 2020-12 semantics: empty schema accepts anything; the FIRST failing
item ends the run with a JSON Pointer to the offending node.
"""

from __future__ import annotations

import pytest
from jsonschema.exceptions import SchemaError

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.errors import ExtractionError
from app.domains.extraction.validator import OutputSchemaValidator


class TestEmptySchema:  # AC-11 (empty {} accepts anything)
    def test_accepts_any_payload(self) -> None:
        v = OutputSchemaValidator({})
        v.validate_all([{"a": 1}, {"b": "x"}, {}])

    def test_empty_items_list_is_fine(self) -> None:
        v = OutputSchemaValidator({})
        v.validate_all([])


class TestFailsFast:  # AC-11 (first failing item ends the run)
    def _schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "required": ["title", "price"],
            "properties": {
                "title": {"type": "string"},
                "price": {"type": "number"},
            },
        }

    def test_valid_items_pass(self) -> None:
        v = OutputSchemaValidator(self._schema())
        v.validate_all([{"title": "a", "price": 1}, {"title": "b", "price": 2.5}])

    def test_missing_required_key_at_index_zero(self) -> None:
        v = OutputSchemaValidator(self._schema())
        with pytest.raises(ExtractionError) as exc:
            v.validate_all([{"title": "a"}, {"title": "b", "price": 1}])
        assert exc.value.code == ExtractionErrorCode.OUTPUT_SCHEMA_MISMATCH
        assert exc.value.details[0]["item_index"] == 0

    def test_wrong_type_reports_pointer_and_index(self) -> None:
        v = OutputSchemaValidator(self._schema())
        with pytest.raises(ExtractionError) as exc:
            v.validate_all(
                [
                    {"title": "a", "price": 1},
                    {"title": "b", "price": "not a number"},
                ]
            )
        assert exc.value.code == ExtractionErrorCode.OUTPUT_SCHEMA_MISMATCH
        assert exc.value.details[0]["item_index"] == 1
        assert exc.value.details[0]["path"] == "/price"
        assert exc.value.details[0]["message"]

    def test_later_items_not_validated_after_first_failure(self) -> None:
        """Second bad item never raises because validation stops at the first."""
        v = OutputSchemaValidator(self._schema())
        with pytest.raises(ExtractionError) as exc:
            v.validate_all(
                [
                    {"title": "a", "price": "bad1"},
                    {"title": "b", "price": "bad2"},
                ]
            )
        assert exc.value.details[0]["item_index"] == 0


class TestJsonPointerEncoding:  # RFC 6901 encoding on the error path
    def test_nested_path_rendered_as_pointer(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "meta": {
                    "type": "object",
                    "properties": {"sku": {"type": "string"}},
                    "required": ["sku"],
                }
            },
            "required": ["meta"],
        }
        v = OutputSchemaValidator(schema)
        with pytest.raises(ExtractionError) as exc:
            v.validate_all([{"meta": {"sku": 42}}])
        assert exc.value.details[0]["path"] == "/meta/sku"

    def test_slash_and_tilde_in_key_are_escaped(self) -> None:
        schema = {
            "type": "object",
            "properties": {"a/b~c": {"type": "string"}},
        }
        v = OutputSchemaValidator(schema)
        with pytest.raises(ExtractionError) as exc:
            v.validate_all([{"a/b~c": 1}])
        # RFC 6901: '/' -> '~1', '~' -> '~0'
        assert exc.value.details[0]["path"] == "/a~1b~0c"

    def test_array_index_in_path(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
        }
        v = OutputSchemaValidator(schema)
        with pytest.raises(ExtractionError) as exc:
            v.validate_all([{"tags": ["ok", 42]}])
        assert exc.value.details[0]["path"] == "/tags/1"


class TestInvalidSchemaRaisesAtConstruction:
    def test_bad_schema_shape_fails_fast(self) -> None:
        with pytest.raises(SchemaError):
            OutputSchemaValidator({"type": "not-a-real-type"})

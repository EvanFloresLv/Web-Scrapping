"""Unit tests for the extractor + output schema validator (spec 0005 AC-6..AC-11).

Reads HTML fixtures from `tests/fixtures/extraction/` so the parse path
is exercised; the DB and HTTP layers are not touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.errors import ExtractionError
from app.domains.extraction.extractor import extract
from app.domains.extraction.parser import parse_html
from app.domains.extraction.validator import OutputSchemaValidator
from app.domains.workflows.config import WorkflowConfig

FIXTURES = Path(__file__).parent / "fixtures" / "extraction"
BASIC_PAGE = (FIXTURES / "catalog_basic" / "page.html").read_bytes()
EMPTY_PRICE_PAGE = (FIXTURES / "empty_price" / "page.html").read_bytes()
FETCHED_URL = "https://example.com/catalog/listing"


def _basic_config(**overrides: Any) -> WorkflowConfig:
    base: dict[str, Any] = {
        "container_selector": "article.product",
        "fields": [
            {
                "name": "title",
                "selector": "h2.title",
                "transforms": ["strip"],
                "type": "string",
            },
            {
                "name": "price",
                "selector": "span.price",
                "transforms": ["strip_currency"],
                "type": "string",
            },
            {
                "name": "link",
                "selector": "a.link",
                "transforms": ["attr:href"],
                "type": "url",
            },
        ],
        "output_schema": {},
    }
    base.update(overrides)
    return WorkflowConfig.model_validate(base)


class TestHappyPath:
    def test_extracts_two_items_with_base_href(self) -> None:
        config = _basic_config()
        doc = parse_html(BASIC_PAGE, charset=None)
        items = extract(doc, config, final_url=FETCHED_URL)
        assert items == [
            {
                "title": "Widget A",
                "price": "12.50",
                "link": "https://example.com/widget-a",
            },
            {
                "title": "Gadget B",
                "price": "3.00",
                "link": "https://example.com/gadget-b",
            },
        ]


class TestContainerMiss:
    def test_zero_matches_raises(self) -> None:
        config = _basic_config(container_selector=".missing")
        doc = parse_html(BASIC_PAGE, charset=None)
        with pytest.raises(ExtractionError) as exc:
            extract(doc, config, final_url=FETCHED_URL)
        assert exc.value.code == ExtractionErrorCode.NO_CONTAINER_MATCH


class TestRequiredField:
    def test_missing_required_field_raises(self) -> None:
        config = _basic_config(
            fields=[
                {
                    "name": "title",
                    "selector": "h2.title",
                    "transforms": [],
                    "type": "string",
                },
                {
                    "name": "missing",
                    "selector": ".nope",
                    "transforms": [],
                    "type": "string",
                    "required": True,
                },
            ]
        )
        doc = parse_html(BASIC_PAGE, charset=None)
        with pytest.raises(ExtractionError) as exc:
            extract(doc, config, final_url=FETCHED_URL)
        assert exc.value.code == ExtractionErrorCode.REQUIRED_FIELD_MISSING
        assert exc.value.details == [{"field": "missing"}]

    def test_optional_field_fills_null(self) -> None:
        config = _basic_config(
            fields=[
                {
                    "name": "title",
                    "selector": "h2.title",
                    "transforms": [],
                    "type": "string",
                },
                {
                    "name": "note",
                    "selector": ".nope",
                    "transforms": [],
                    "type": "string",
                    "required": False,
                },
            ]
        )
        doc = parse_html(BASIC_PAGE, charset=None)
        items = extract(doc, config, final_url=FETCHED_URL)
        assert items[0]["note"] is None


class TestEmptyMatch:
    def test_empty_text_is_a_legitimate_match(self) -> None:
        """A required field whose selector matches an empty element returns ''."""
        config = _basic_config(
            fields=[
                {
                    "name": "price",
                    "selector": "span.price",
                    "transforms": [],
                    "type": "string",
                },
            ]
        )
        doc = parse_html(EMPTY_PRICE_PAGE, charset=None)
        items = extract(doc, config, final_url=FETCHED_URL)
        assert items == [{"price": ""}]


class TestTypeCoercionFailure:
    def test_bad_decimal_raises(self) -> None:
        config = _basic_config(
            fields=[
                {
                    "name": "price",
                    "selector": "h2.title",
                    "transforms": [],
                    "type": "decimal",
                },
            ]
        )
        doc = parse_html(BASIC_PAGE, charset=None)
        with pytest.raises(ExtractionError) as exc:
            extract(doc, config, final_url=FETCHED_URL)
        assert exc.value.code == ExtractionErrorCode.TYPE_COERCION_ERROR


class TestSelectorSyntaxError:
    def test_bad_container_selector(self) -> None:
        config = _basic_config(container_selector="::::bad")
        doc = parse_html(BASIC_PAGE, charset=None)
        with pytest.raises(ExtractionError) as exc:
            extract(doc, config, final_url=FETCHED_URL)
        # selectolax may either raise or match nothing; either outcome
        # surfaces as a stable extraction code.
        assert exc.value.code in {
            ExtractionErrorCode.SELECTOR_SYNTAX_ERROR,
            ExtractionErrorCode.NO_CONTAINER_MATCH,
        }


class TestOutputSchemaValidator:
    def test_empty_schema_accepts_anything(self) -> None:
        v = OutputSchemaValidator({})
        v.validate_all([{"x": 1}, {"y": "z"}])

    def test_first_bad_item_raises_with_pointer(self) -> None:
        schema = {
            "type": "object",
            "required": ["title", "price"],
            "properties": {
                "title": {"type": "string"},
                "price": {"type": "number"},
            },
        }
        v = OutputSchemaValidator(schema)
        with pytest.raises(ExtractionError) as exc:
            v.validate_all(
                [
                    {"title": "Widget", "price": 1},
                    {"title": "Gadget", "price": "nope"},
                ]
            )
        assert exc.value.code == ExtractionErrorCode.OUTPUT_SCHEMA_MISMATCH
        assert exc.value.details
        assert exc.value.details[0]["item_index"] == 1
        assert exc.value.details[0]["path"] == "/price"

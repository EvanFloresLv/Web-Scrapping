"""Unit tests for field type coercion (spec 0005 AC-10)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.coercion import coerce
from app.domains.extraction.errors import ExtractionError

BASE = "https://example.com/catalog/"


class TestString:
    def test_identity(self) -> None:
        assert coerce("hi", type_name="string", field="t", base_url=BASE) == "hi"


class TestInteger:
    def test_parses(self) -> None:
        assert coerce(" 7 ", type_name="integer", field="n", base_url=BASE) == 7

    def test_rejects_non_numeric(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            coerce("abc", type_name="integer", field="n", base_url=BASE)
        assert exc.value.code == ExtractionErrorCode.TYPE_COERCION_ERROR


class TestDecimal:
    def test_parses(self) -> None:
        value = coerce("3.14", type_name="decimal", field="p", base_url=BASE)
        assert value == Decimal("3.14")

    def test_rejects_non_numeric(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            coerce("not a number", type_name="decimal", field="p", base_url=BASE)
        assert exc.value.code == ExtractionErrorCode.TYPE_COERCION_ERROR


class TestBoolean:
    @pytest.mark.parametrize("value", ["true", "1", "yes", "ON"])
    def test_truthy(self, value: str) -> None:
        assert coerce(value, type_name="boolean", field="b", base_url=BASE) is True

    @pytest.mark.parametrize("value", ["false", "0", "No", "off"])
    def test_falsy(self, value: str) -> None:
        assert coerce(value, type_name="boolean", field="b", base_url=BASE) is False

    def test_rejects_other(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            coerce("maybe", type_name="boolean", field="b", base_url=BASE)
        assert exc.value.code == ExtractionErrorCode.TYPE_COERCION_ERROR


class TestUrl:
    def test_absolute(self) -> None:
        got = coerce(
            "https://other.com/x",
            type_name="url",
            field="u",
            base_url=BASE,
        )
        assert got == "https://other.com/x"

    def test_relative_resolves_against_base(self) -> None:
        got = coerce("/widget", type_name="url", field="u", base_url=BASE)
        assert got == "https://example.com/widget"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            coerce("", type_name="url", field="u", base_url=BASE)
        assert exc.value.code == ExtractionErrorCode.TYPE_COERCION_ERROR


class TestUnknownType:
    def test_falls_back_to_type_coercion_error(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            coerce("x", type_name="binary", field="t", base_url=BASE)
        assert exc.value.code == ExtractionErrorCode.TYPE_COERCION_ERROR

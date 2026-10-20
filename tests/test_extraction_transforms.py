"""Unit tests for the extraction transform pipeline (spec 0005 AC-9)."""

from __future__ import annotations

import pytest

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.errors import ExtractionError
from app.domains.extraction.transforms import (
    apply_scalar,
    is_attr_transform,
    parse_attr_name,
)


class TestTextNormalizers:
    def test_strip(self) -> None:
        assert apply_scalar("  hi  ", "strip", field="t") == "hi"

    def test_collapse_whitespace(self) -> None:
        assert apply_scalar(" a   b\tc\n", "collapse_whitespace", field="t") == "a b c"

    def test_lower(self) -> None:
        assert apply_scalar("ABC", "lower", field="t") == "abc"

    def test_upper(self) -> None:
        assert apply_scalar("abc", "upper", field="t") == "ABC"


class TestNumericParsers:
    def test_to_int(self) -> None:
        assert apply_scalar(" 42 ", "to_int", field="n") == "42"

    def test_to_int_rejects_non_numeric(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            apply_scalar("abc", "to_int", field="n")
        assert exc.value.code == ExtractionErrorCode.TRANSFORM_ERROR

    def test_to_decimal_en_default(self) -> None:
        assert apply_scalar("1,234.56", "to_decimal", field="n") == "1234.56"

    def test_to_decimal_de(self) -> None:
        assert apply_scalar("1.234,56", "to_decimal:de", field="n") == "1234.56"

    def test_strip_currency(self) -> None:
        assert apply_scalar(" $12.50 ", "strip_currency", field="n") == "12.50"


class TestRegex:
    def test_regex_extract_group1(self) -> None:
        assert apply_scalar("Price: 42 USD", r"regex_extract:(\d+)", field="n") == "42"

    def test_regex_extract_no_group_returns_full_match(self) -> None:
        assert apply_scalar("abc42xyz", r"regex_extract:\d+", field="n") == "42"

    def test_regex_extract_no_match_raises(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            apply_scalar("abc", r"regex_extract:\d+", field="n")
        assert exc.value.code == ExtractionErrorCode.TRANSFORM_ERROR

    def test_regex_replace_simple(self) -> None:
        assert apply_scalar("Hello world", r"regex_replace:world:there", field="t") == "Hello there"

    def test_regex_replace_requires_replacement(self) -> None:
        with pytest.raises(ExtractionError):
            apply_scalar("x", r"regex_replace:abc", field="t")

    def test_regex_replace_escaped_colon(self) -> None:
        # Pattern `a\:b` (literal `a:b`), replacement `x`.
        assert apply_scalar("za:bz", r"regex_replace:a\:b:x", field="t") == "zxz"


class TestAttrTransform:
    def test_is_attr_transform(self) -> None:
        assert is_attr_transform("attr:href")
        assert is_attr_transform("attr")
        assert not is_attr_transform("strip")

    def test_parse_attr_name(self) -> None:
        assert parse_attr_name("attr:href") == "href"

    def test_parse_attr_name_missing_colon(self) -> None:
        with pytest.raises(ExtractionError):
            parse_attr_name("attr")

    def test_apply_scalar_rejects_attr_mid_pipeline(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            apply_scalar("ignored", "attr:href", field="link")
        assert exc.value.code == ExtractionErrorCode.TRANSFORM_ERROR


class TestUnknownTransform:
    def test_unknown_name(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            apply_scalar("x", "nope", field="t")
        assert exc.value.code == ExtractionErrorCode.TRANSFORM_ERROR

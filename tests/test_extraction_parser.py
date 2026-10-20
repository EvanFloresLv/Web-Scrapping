"""Unit tests for the HTML parser helpers (spec 0005 AC-6, AC-10).

Covers decoding, CSS selection error mapping, and `<base href>` lookup
used by `url` type coercion.
"""

from __future__ import annotations

import pytest

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.errors import ExtractionError
from app.domains.extraction.parser import (
    css_select_all,
    css_select_first,
    find_base_href,
    parse_html,
)


class TestParseHtml:
    def test_decodes_with_provided_charset(self) -> None:
        body = "<p>áé</p>".encode("latin-1")
        doc = parse_html(body, charset="latin-1")
        node = doc.css_first("p")
        assert node is not None
        assert node.text() == "áé"

    def test_falls_back_to_utf8_when_charset_is_none(self) -> None:
        body = "<p>日本</p>".encode()
        doc = parse_html(body, charset=None)
        node = doc.css_first("p")
        assert node is not None
        assert node.text() == "日本"

    def test_unknown_charset_falls_back_to_utf8(self) -> None:
        body = b"<p>ok</p>"
        doc = parse_html(body, charset="not-a-real-encoding")
        assert doc.css_first("p") is not None

    def test_undecodable_bytes_use_replace_errors(self) -> None:
        body = b"<p>\xff\xfe\x00bad</p>"
        doc = parse_html(body, charset="utf-8")
        assert doc.css_first("p") is not None


class TestCssSelectAll:  # AC-6
    def test_returns_matches_in_document_order(self) -> None:
        doc = parse_html(b"<ul><li>a</li><li>b</li><li>c</li></ul>", charset=None)
        nodes = css_select_all(doc, "li", where="items")
        assert [n.text() for n in nodes] == ["a", "b", "c"]

    def test_empty_match_returns_empty_list(self) -> None:
        doc = parse_html(b"<p>x</p>", charset=None)
        assert css_select_all(doc, ".missing", where="field") == []

    def test_bad_selector_raises_selector_syntax_error(self) -> None:
        doc = parse_html(b"<p>x</p>", charset=None)
        with pytest.raises(ExtractionError) as exc:
            css_select_all(doc, "::::bad", where="price")
        assert exc.value.code == ExtractionErrorCode.SELECTOR_SYNTAX_ERROR
        assert exc.value.details[0]["field"] == "price"
        assert "message" in exc.value.details[0]

    def test_bad_container_selector_uses_container_label(self) -> None:
        doc = parse_html(b"<p>x</p>", charset=None)
        with pytest.raises(ExtractionError) as exc:
            css_select_all(doc, "::::bad", where="container_selector")
        assert exc.value.details[0]["field"] == "container_selector"


class TestCssSelectFirst:
    def test_returns_first_match(self) -> None:
        doc = parse_html(b"<ul><li>a</li><li>b</li></ul>", charset=None)
        node = css_select_first(doc, "li", where="field")
        assert node is not None
        assert node.text() == "a"

    def test_returns_none_on_no_match(self) -> None:
        doc = parse_html(b"<p>x</p>", charset=None)
        assert css_select_first(doc, ".missing", where="field") is None

    def test_propagates_selector_syntax_error(self) -> None:
        doc = parse_html(b"<p>x</p>", charset=None)
        with pytest.raises(ExtractionError) as exc:
            css_select_first(doc, "::::bad", where="field")
        assert exc.value.code == ExtractionErrorCode.SELECTOR_SYNTAX_ERROR


class TestFindBaseHref:  # AC-10
    def test_returns_href_when_present(self) -> None:
        doc = parse_html(b"<html><head><base href='https://ex.com/'></head></html>", charset=None)
        assert find_base_href(doc) == "https://ex.com/"

    def test_returns_none_when_absent(self) -> None:
        doc = parse_html(b"<html><head></head></html>", charset=None)
        assert find_base_href(doc) is None

    def test_returns_first_when_multiple(self) -> None:
        doc = parse_html(
            b"<head><base href='https://a.com/'><base href='https://b.com/'></head>",
            charset=None,
        )
        assert find_base_href(doc) == "https://a.com/"

    def test_base_without_href_attribute_returns_none(self) -> None:
        doc = parse_html(b"<head><base></head></html>", charset=None)
        assert find_base_href(doc) is None

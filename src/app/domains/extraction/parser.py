"""HTML parsing + CSS selection on top of selectolax (spec 0005 AC-6).

selectolax wraps Lexbor, a fast C HTML5 parser. We only need two things:
parse the fetched body into a document, and run CSS selectors against it.
A selector that selectolax rejects as unparseable surfaces at the
extractor layer as `extraction.selector_syntax_error` (AC-6).
"""

from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.errors import ExtractionError


def parse_html(body: bytes, charset: str | None) -> LexborHTMLParser:
    """Decode `body` using `charset` (fallback UTF 8) and parse to a document."""
    encoding = (charset or "utf-8").lower()
    try:
        text = body.decode(encoding, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    return LexborHTMLParser(text)


def css_select_all(
    scope: LexborHTMLParser | LexborNode,
    selector: str,
    *,
    where: str,
) -> list[LexborNode]:
    """Run a CSS selector; raise `extraction.selector_syntax_error` on parse failure.

    `where` is the human readable label for the selector (either the field
    name or the literal string `container_selector`) so the error details
    tell operators which selector blew up.
    """
    try:
        return list(scope.css(selector))
    except Exception as exc:  # selectolax raises bare Exception on bad CSS
        raise ExtractionError(
            ExtractionErrorCode.SELECTOR_SYNTAX_ERROR,
            f"selector for {where!r} is not a valid CSS selector",
            details=[{"field": where, "message": str(exc)}],
        ) from exc


def css_select_first(
    scope: LexborHTMLParser | LexborNode,
    selector: str,
    *,
    where: str,
) -> LexborNode | None:
    """Return the first matching node or None; raises on bad selector syntax."""
    matches = css_select_all(scope, selector, where=where)
    return matches[0] if matches else None


def find_base_href(document: LexborHTMLParser) -> str | None:
    """Return the first `<base href=...>` on the page, or None (AC-10 for `url` coercion)."""
    node = document.css_first("base[href]")
    if node is None:
        return None
    href = node.attributes.get("href")
    return href if href is None else str(href)

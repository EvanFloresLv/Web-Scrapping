"""Transform pipeline for extracted field values (spec 0005 AC-9).

The MVP transform set:

- Text normalizers (no args): `strip`, `collapse_whitespace`, `lower`, `upper`.
- Attribute picker: `attr:<name>` (must be the FIRST transform if present).
- Numeric and money parsers: `to_int`, `to_decimal` (optional locale arg
  `to_decimal:en` or `to_decimal:de`; default `en`), `strip_currency`.
- Regex: `regex_extract:<pattern>`, `regex_replace:<pattern>:<replacement>`
  (`:` inside the pattern or replacement must be escaped as `\\:`).

An unknown transform name raises `ExtractionError(TRANSFORM_ERROR)`.

Values flow as `str` through the pipeline. The `attr:<name>` picker runs
on the matched element and switches the current value to that attribute;
every other transform operates on the running string. The first non `attr:`
transform forces the value to the element's `text()` if the element is
still live (handled by the extractor before this module runs).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Final

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.errors import ExtractionError

_CURRENCY_CHARS: Final[str] = "$€£¥¢"
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


def _unescape_colons(fragment: str) -> str:
    return fragment.replace("\\:", ":")


def _split_regex_replace_args(raw: str) -> tuple[str, str]:
    """Split a `regex_replace` argument string on an unescaped `:`.

    Returns `(pattern, replacement)`. An unescaped `:` separates them; an
    escaped `\\:` stays part of the previous side.
    """
    i = 0
    buf: list[str] = []
    pattern: str | None = None
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw) and raw[i + 1] == ":":
            buf.append(":")
            i += 2
            continue
        if ch == ":" and pattern is None:
            pattern = "".join(buf)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if pattern is None:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            "regex_replace requires a replacement separated by ':'",
            details=[{"transform": "regex_replace", "reason": "missing replacement"}],
        )
    return pattern, "".join(buf)


def _text_strip(value: str) -> str:
    return value.strip()


def _text_collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _text_lower(value: str) -> str:
    return value.lower()


def _text_upper(value: str) -> str:
    return value.upper()


def _strip_currency(value: str) -> str:
    cleaned = value
    for sym in _CURRENCY_CHARS:
        cleaned = cleaned.replace(sym, "")
    return cleaned.strip()


def _to_int(value: str, *, field: str) -> str:
    try:
        return str(int(value.strip()))
    except ValueError as exc:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            f"to_int could not parse {value!r}",
            details=[{"field": field, "transform": "to_int", "reason": str(exc)}],
        ) from exc


def _to_decimal(value: str, *, locale: str, field: str) -> str:
    stripped = value.strip()
    if locale == "en":
        normalized = stripped.replace(",", "")
    elif locale == "de":
        normalized = stripped.replace(".", "").replace(",", ".")
    else:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            f"to_decimal locale {locale!r} not supported",
            details=[{"field": field, "transform": "to_decimal", "locale": locale}],
        )
    try:
        return str(Decimal(normalized))
    except InvalidOperation as exc:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            f"to_decimal could not parse {value!r}",
            details=[{"field": field, "transform": "to_decimal", "reason": str(exc)}],
        ) from exc


def _regex_extract(value: str, pattern: str, *, field: str) -> str:
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            f"regex_extract pattern {pattern!r} failed to compile",
            details=[{"field": field, "transform": "regex_extract", "reason": str(exc)}],
        ) from exc
    match = compiled.search(value)
    if match is None:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            f"regex_extract did not match in {value!r}",
            details=[{"field": field, "transform": "regex_extract", "pattern": pattern}],
        )
    if compiled.groups >= 1:
        group = match.group(1)
        return "" if group is None else group
    return match.group(0)


def _regex_replace(value: str, pattern: str, replacement: str, *, field: str) -> str:
    try:
        return re.sub(pattern, replacement, value)
    except re.error as exc:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            f"regex_replace pattern {pattern!r} failed",
            details=[{"field": field, "transform": "regex_replace", "reason": str(exc)}],
        ) from exc


# Names registered here are the complete allow list. Feature 5's publish-time
# validator may import this list once the follow-up re-wires that check.
NO_ARG_TRANSFORMS: frozenset[str] = frozenset(
    {"strip", "collapse_whitespace", "lower", "upper", "strip_currency", "to_int"}
)
ARG_TRANSFORM_PREFIXES: frozenset[str] = frozenset(
    {"attr", "to_decimal", "regex_extract", "regex_replace"}
)

_NO_ARG_FUNCS: dict[str, Callable[[str], str]] = {
    "strip": _text_strip,
    "collapse_whitespace": _text_collapse_whitespace,
    "lower": _text_lower,
    "upper": _text_upper,
    "strip_currency": _strip_currency,
}


def is_attr_transform(name: str) -> bool:
    return name == "attr" or name.startswith("attr:")


def parse_attr_name(name: str) -> str:
    """Return the attribute name from an `attr:<name>` transform."""
    if ":" not in name:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            "attr transform requires an attribute name (attr:<name>)",
            details=[{"transform": name, "reason": "missing attribute name"}],
        )
    _, attr = name.split(":", 1)
    attr = attr.strip()
    if not attr:
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            "attr transform requires a non empty attribute name",
            details=[{"transform": name, "reason": "empty attribute name"}],
        )
    return attr


def apply_scalar(value: str, name: str, *, field: str) -> str:
    """Apply a single scalar transform; raise `ExtractionError` on failure.

    `attr:<name>` is NOT handled here; it operates on the element before
    the string pipeline starts and must be dispatched by the extractor.
    """
    if is_attr_transform(name):
        raise ExtractionError(
            ExtractionErrorCode.TRANSFORM_ERROR,
            "attr transform must be the first transform in the pipeline",
            details=[{"field": field, "transform": name}],
        )

    if name in _NO_ARG_FUNCS:
        return _NO_ARG_FUNCS[name](value)
    if name == "to_int":
        return _to_int(value, field=field)

    head, _, raw_args = name.partition(":")
    if head == "to_decimal":
        locale = raw_args or "en"
        return _to_decimal(value, locale=locale, field=field)
    if head == "regex_extract":
        if not raw_args:
            raise ExtractionError(
                ExtractionErrorCode.TRANSFORM_ERROR,
                "regex_extract requires a pattern",
                details=[{"field": field, "transform": "regex_extract"}],
            )
        return _regex_extract(value, _unescape_colons(raw_args), field=field)
    if head == "regex_replace":
        if not raw_args:
            raise ExtractionError(
                ExtractionErrorCode.TRANSFORM_ERROR,
                "regex_replace requires a pattern:replacement argument",
                details=[{"field": field, "transform": "regex_replace"}],
            )
        pattern, replacement = _split_regex_replace_args(raw_args)
        return _regex_replace(value, pattern, replacement, field=field)

    raise ExtractionError(
        ExtractionErrorCode.TRANSFORM_ERROR,
        f"unknown transform {name!r}",
        details=[{"field": field, "transform": name}],
    )

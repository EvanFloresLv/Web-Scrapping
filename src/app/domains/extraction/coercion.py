"""Field type coercion (spec 0005 AC-10).

Allowed values: `string | integer | decimal | boolean | url`.

- `string`: identity.
- `integer`: `int(value.strip())`; failure → extraction.type_coercion_error.
- `decimal`: `Decimal(value)` (money rule from AGENTS.md: never float).
- `boolean`: case insensitive {true,1,yes,on} / {false,0,no,off}; anything
  else → extraction.type_coercion_error.
- `url`: parsed as absolute; a relative URL is resolved against
  `<base href>` if present, else against the fetched URL (post redirect).

The decimal coercion returns a `Decimal` as the JSON wire value; the
Pydantic encoder on the preview endpoint serialises it as a string per
AGENTS.md ("money as Decimal").

An unknown type string also returns type_coercion_error; feature 5's
publish-time validator should reject unknown types up front, but the run
time path is the backstop.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.errors import ExtractionError

_BOOL_TRUE = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE = frozenset({"false", "0", "no", "off"})

ALLOWED_TYPES: frozenset[str] = frozenset({"string", "integer", "decimal", "boolean", "url"})


def coerce(
    value: str,
    *,
    type_name: str,
    field: str,
    base_url: str,
) -> Any:
    """Coerce `value` to the declared field type; raise on failure.

    `base_url` is the URL used to resolve relative `url` values (either the
    page's `<base href>` or the final fetched URL post-redirect).
    """
    if type_name == "string":
        return value
    if type_name == "integer":
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ExtractionError(
                ExtractionErrorCode.TYPE_COERCION_ERROR,
                f"cannot coerce {value!r} to integer",
                details=[{"field": field, "type": "integer", "value": value}],
            ) from exc
    if type_name == "decimal":
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise ExtractionError(
                ExtractionErrorCode.TYPE_COERCION_ERROR,
                f"cannot coerce {value!r} to decimal",
                details=[{"field": field, "type": "decimal", "value": value}],
            ) from exc
    if type_name == "boolean":
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ExtractionError(
            ExtractionErrorCode.TYPE_COERCION_ERROR,
            f"cannot coerce {value!r} to boolean",
            details=[{"field": field, "type": "boolean", "value": value}],
        )
    if type_name == "url":
        candidate = value.strip()
        if not candidate:
            raise ExtractionError(
                ExtractionErrorCode.TYPE_COERCION_ERROR,
                "empty url value",
                details=[{"field": field, "type": "url", "value": value}],
            )
        resolved = urljoin(base_url, candidate)
        return resolved

    raise ExtractionError(
        ExtractionErrorCode.TYPE_COERCION_ERROR,
        f"unknown field type {type_name!r}",
        details=[{"field": field, "type": type_name}],
    )

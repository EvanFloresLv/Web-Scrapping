"""`output_schema` validation using jsonschema draft 2020-12 (spec 0005 AC-11).

Fail-fast: the FIRST item that fails validation ends the execution with
`extraction.output_schema_mismatch`; later items are not validated this
pass (a future spec may add `validate_all` for repair flows).

Empty schema `{}` accepts anything (JSON Schema semantics). The validator
is instantiated once per execution so the schema compile cost is paid once.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.errors import ExtractionError


def _json_pointer_from_path(path_parts: list[Any]) -> str:
    """Render a jsonschema error path as an RFC 6901 JSON Pointer."""
    if not path_parts:
        return ""
    encoded = []
    for part in path_parts:
        text = str(part).replace("~", "~0").replace("/", "~1")
        encoded.append(text)
    return "/" + "/".join(encoded)


class OutputSchemaValidator:
    """Validate every item in order; raise on the first failure (AC-11)."""

    def __init__(self, schema: dict[str, Any]) -> None:
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)

    def validate_all(self, items: list[dict[str, Any]]) -> None:
        for index, item in enumerate(items):
            try:
                self._validator.validate(item)
            except JsonSchemaValidationError as exc:
                pointer = _json_pointer_from_path(list(exc.absolute_path))
                raise ExtractionError(
                    ExtractionErrorCode.OUTPUT_SCHEMA_MISMATCH,
                    f"item {index} does not match output_schema: {exc.message}",
                    details=[
                        {
                            "item_index": index,
                            "path": pointer,
                            "message": exc.message,
                        }
                    ],
                ) from exc

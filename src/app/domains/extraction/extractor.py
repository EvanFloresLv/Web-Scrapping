"""Container + field extractor (spec 0005 AC-7, AC-8).

Workflow:

1. Find all top-level nodes matching `container_selector`. Zero matches →
   `extraction.no_container_match`.
2. For each container, build one item dict by iterating `fields` in order:
   - If the field has `attr:<name>` as its FIRST transform, pick that
     attribute off the matched element; otherwise take `element.text()`.
   - Apply the remaining transforms left to right.
   - Coerce to the declared `type`.
   - Missing selector match on a `required=True` field →
     `extraction.required_field_missing`; `required=False` stores `null`.
3. Return the list of item dicts in document order.
"""

from __future__ import annotations

from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.core.errors.execution_codes import ExtractionErrorCode
from app.domains.extraction.coercion import coerce
from app.domains.extraction.errors import ExtractionError
from app.domains.extraction.parser import (
    css_select_all,
    css_select_first,
    find_base_href,
)
from app.domains.extraction.transforms import (
    apply_scalar,
    is_attr_transform,
    parse_attr_name,
)
from app.domains.workflows.config import FieldSpec, WorkflowConfig


def _resolve_base_url(document: LexborHTMLParser, final_url: str) -> str:
    """Return the base URL for `url` type coercion (AC-10).

    `<base href>` wins when present; otherwise the post-redirect fetched URL.
    """
    base_href = find_base_href(document)
    if base_href is None:
        return final_url
    from urllib.parse import urljoin

    return urljoin(final_url, base_href)


def _extract_field_raw(
    container: LexborNode,
    field: FieldSpec,
) -> tuple[LexborNode | None, str | None, list[str]]:
    """Return `(element, raw_value, remaining_transforms)`.

    - `(None, None, _)`: zero matches.
    - `(element, attr_value, remaining)`: first transform was `attr:<name>`;
      the attribute may be `None` if absent on the element.
    - `(element, None, transforms)`: no `attr:` prefix; caller should read
      `element.text()` before running the string pipeline.
    """
    element = css_select_first(container, field.selector, where=field.name)
    if element is None:
        return None, None, list(field.transforms)

    transforms = list(field.transforms)
    if transforms and is_attr_transform(transforms[0]):
        attr = parse_attr_name(transforms[0])
        value = element.attributes.get(attr)
        return element, value, transforms[1:]
    return element, None, transforms


def extract(
    document: LexborHTMLParser,
    config: WorkflowConfig,
    *,
    final_url: str,
) -> list[dict[str, Any]]:
    """Run the configured extraction over the parsed document.

    Returns one item per container node (document order). Raises
    `ExtractionError` with a stable code on any failure in the pipeline.
    """
    containers = css_select_all(document, config.container_selector, where="container_selector")
    if not containers:
        raise ExtractionError(
            ExtractionErrorCode.NO_CONTAINER_MATCH,
            f"container selector {config.container_selector!r} matched zero elements",
            details=[{"selector": config.container_selector}],
        )

    base_url = _resolve_base_url(document, final_url)
    items: list[dict[str, Any]] = []
    for container in containers:
        item: dict[str, Any] = {}
        for field in config.fields:
            element, attr_value, remaining = _extract_field_raw(container, field)
            if element is None:
                if field.required:
                    raise ExtractionError(
                        ExtractionErrorCode.REQUIRED_FIELD_MISSING,
                        f"required field {field.name!r} matched zero elements",
                        details=[{"field": field.name}],
                    )
                item[field.name] = None
                continue

            if attr_value is None and (
                not field.transforms or not is_attr_transform(field.transforms[0])
            ):
                value: str = element.text() or ""
            elif attr_value is None:
                value = ""
            else:
                value = attr_value

            for transform in remaining:
                value = apply_scalar(value, transform, field=field.name)

            item[field.name] = coerce(
                value,
                type_name=field.type,
                field=field.name,
                base_url=base_url,
            )
        items.append(item)

    return items

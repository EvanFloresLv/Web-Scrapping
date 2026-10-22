"""Opaque cursor codec for the execution browser list (spec 0010 AC-2).

Encodes a `(created_at, id)` pair as `base64url(JSON.stringify({c, i}))`
so the client treats the cursor as a token. The server round-trips it on
every page; `(created_at, id) < (c, i)` is the keyset predicate the
repository applies on the `(created_at DESC, id DESC)` sort.

Both sides of the pair are strictly required so the sort has a total
order even for executions that land in the same millisecond.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.errors import ErrorDetail
from app.domains.executions.errors import InvalidCursorError


@dataclass(frozen=True)
class Cursor:
    """Decoded cursor payload.

    `created_at` is a timezone-aware UTC datetime (matching the column
    convention pinned in `AGENTS.md`). `id` is the row's UUIDv7.
    """

    created_at: datetime
    id: UUID


def encode_cursor(created_at: datetime, row_id: UUID) -> str:
    """Encode `(created_at, id)` to the wire string.

    The output is URL-safe (no `+`, `/`, or `=` padding), so it survives
    both query string placement and copy-paste into a chat.
    """
    payload = json.dumps(
        {"c": created_at.isoformat(), "i": str(row_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_cursor(raw: str) -> Cursor:
    """Decode a wire cursor back to `(created_at, id)`.

    Raises `InvalidCursorError` on any shape failure: base64 decode error,
    non-JSON body, missing/extra keys, bad ISO-8601 timestamp, bad UUID.
    """
    if not raw:
        _raise("cursor is empty")
    try:
        # Re-add padding stripped on encode (base64 requires a multiple of 4).
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, TypeError) as exc:
        _raise(f"cursor is not valid base64url: {exc}")
    try:
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError) as exc:
        _raise(f"cursor body is not valid JSON: {exc}")
    if not isinstance(payload, dict) or set(payload.keys()) != {"c", "i"}:
        _raise("cursor must be a JSON object with exactly keys 'c' and 'i'")
    try:
        created_at = datetime.fromisoformat(str(payload["c"]))
    except (TypeError, ValueError) as exc:
        _raise(f"cursor 'c' is not a valid ISO-8601 datetime: {exc}")
    try:
        row_id = UUID(str(payload["i"]))
    except (TypeError, ValueError) as exc:
        _raise(f"cursor 'i' is not a valid UUID: {exc}")
    return Cursor(created_at=created_at, id=row_id)


def _raise(message: str) -> None:
    raise InvalidCursorError(
        "cursor is malformed",
        errors=[
            ErrorDetail(
                code=InvalidCursorError.code,
                loc=["query", "cursor"],
                message=message,
            )
        ],
    )


__all__ = ["Cursor", "decode_cursor", "encode_cursor"]

"""Cursor codec for the execution browser list (spec 0010 AC-2).

Round trips, URL safety, and every malformed shape surface as the
`execution.invalid_cursor` Problem Details error.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.domains.executions.cursor import Cursor, decode_cursor, encode_cursor
from app.domains.executions.errors import InvalidCursorError

TS = datetime(2026, 10, 21, 12, 34, 56, 789000, tzinfo=UTC)
ID = UUID("01a15a1d-b50d-72a8-b64f-a7a462ed90b2")


class TestEncode:
    def test_round_trip_preserves_both_fields(self) -> None:
        # covers: AC-2
        encoded = encode_cursor(TS, ID)
        decoded = decode_cursor(encoded)
        assert decoded == Cursor(created_at=TS, id=ID)

    def test_output_is_url_safe_and_unpadded(self) -> None:
        # covers: AC-2 (survives placement in a URL and copy paste)
        encoded = encode_cursor(TS, ID)
        assert "/" not in encoded
        assert "+" not in encoded
        assert "=" not in encoded

    def test_decode_tolerates_missing_padding(self) -> None:
        # covers: AC-2 (we strip padding on encode and re-add on decode)
        encoded = encode_cursor(TS, ID)
        padded = encoded + "=="  # extra padding should be harmless
        assert decode_cursor(padded) == Cursor(created_at=TS, id=ID)


class TestDecodeFailures:
    @pytest.mark.parametrize(
        ("raw", "expected_fragment"),
        [
            ("", "empty"),
            ("not!base64@@", "not valid base64url"),
            (base64.urlsafe_b64encode(b"not json at all").decode(), "not valid JSON"),
            (
                base64.urlsafe_b64encode(b'{"c":"2026-10-21T00:00:00+00:00"}').decode(),
                "'c' and 'i'",
            ),
            (
                base64.urlsafe_b64encode(
                    b'{"c":"not a date","i":"01a15a1d-b50d-72a8-b64f-a7a462ed90b2"}'
                ).decode(),
                "ISO-8601",
            ),
            (
                base64.urlsafe_b64encode(
                    b'{"c":"2026-10-21T00:00:00+00:00","i":"not a uuid"}'
                ).decode(),
                "UUID",
            ),
        ],
    )
    def test_malformed_cursors_raise_invalid_cursor(
        self,
        raw: str,
        expected_fragment: str,
    ) -> None:
        # covers: AC-2 (every malformed shape surfaces as execution.invalid_cursor)
        with pytest.raises(InvalidCursorError) as exc_info:
            decode_cursor(raw)
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == "execution.invalid_cursor"
        joined = " ".join(e.message for e in exc_info.value.errors)
        assert expected_fragment in joined

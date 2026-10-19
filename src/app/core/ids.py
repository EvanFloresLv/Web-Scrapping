"""Application side UUIDv7 generation.

Spec 0001 pins UUIDv7 for every primary key. UUIDv7 is time ordered, so inserts
stay index friendly and the id doubles as a cursor on `created_at` style sorts.
This module is the one place every ORM default pulls from, so a future generator
swap is a single file change.
"""

from __future__ import annotations

from uuid import UUID

import uuid_utils


def uuid_v7() -> UUID:
    """Return a fresh UUIDv7 as a stdlib `uuid.UUID`.

    `uuid_utils.uuid7()` returns its own `UUID` type; we normalise to the stdlib
    class so SQLAlchemy, Pydantic, and the rest of the codebase see one type.
    """
    return UUID(str(uuid_utils.uuid7()))

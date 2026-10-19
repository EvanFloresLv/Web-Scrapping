"""Central registry for `executions.error_code` values (spec 0003, AC-17).

Error codes stored on `executions.error_code` are domain prefixed dotted strings.
The column stays plain `text` (no DB CHECK), so adding a code is a code change,
not a migration. This file is the single source of truth every writer imports
from.

Prefixes and their owning slice features:

- `fetch.*`     : HTTP fetch failures (feature 6, deterministic HTML extraction).
- `extraction.*`: deterministic extractor failures (feature 6).
- `execution.*` : executor service failures (feature 7, execution endpoint).
- `agent.*`     : LLM assisted path failures (feature 15 and beyond).

Each slice feature extends its own prefix by adding members to the enum below;
no slice invents a new prefix without updating this docstring. The `StrEnum`
shape lets both the writer (service layer) and the reader (admin UI) share one
contract, and keeps every code sortable, grep friendly, and stable across runs.

This spec (0003) deliberately ships the empty shells. The slice features that
produce the errors populate them.
"""

from __future__ import annotations

from enum import StrEnum


class FetchErrorCode(StrEnum):
    """HTTP fetch failures. Populated by feature 6."""


class ExtractionErrorCode(StrEnum):
    """Deterministic extractor failures. Populated by feature 6."""


class ExecutionErrorCode(StrEnum):
    """Executor service failures. Populated by feature 7."""


class AgentErrorCode(StrEnum):
    """LLM assisted path failures. Populated by feature 15 and beyond."""


# Convenience union used by writer-side type hints once concrete codes land.
ExecutionErrorCodeValue = FetchErrorCode | ExtractionErrorCode | ExecutionErrorCode | AgentErrorCode

__all__ = [
    "AgentErrorCode",
    "ExecutionErrorCode",
    "ExecutionErrorCodeValue",
    "ExtractionErrorCode",
    "FetchErrorCode",
]

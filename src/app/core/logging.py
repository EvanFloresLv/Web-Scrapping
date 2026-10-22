"""Structured logging setup.

Spec 0011 is the authoritative contract. Spec 0001 pinned the stack
(`structlog` + `asgi-correlation-id`). Every event the platform emits
flows through the processor chain assembled here:

    merge_contextvars -> TimeStamper -> add_log_level
    -> StackInfoRenderer -> format_exc_info
    -> ensure_correlation_id -> redact_sensitive_keys
    -> safe_render(renderer)

The pin matters: `redact_sensitive_keys` runs AFTER `merge_contextvars`
(so secrets bound into contextvars are redacted too) and BEFORE the
renderer (so the rendered JSON never sees a raw secret). `safe_render`
is the outermost wrapper so a renderer blow up never crashes callers.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any

import structlog
from asgi_correlation_id import CorrelationIdFilter

from app.core.config import Settings

SENSITIVE_LOG_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "authorization",
        "password",
        "token",
        "cookie",
        "set-cookie",
        "x-api-key",
    }
)
"""Spec 0011 AC-6: event-dict keys whose values are replaced with
`"<redacted>"` by the `redact_sensitive_keys` processor, matched case
insensitively. Recursive one level into nested dicts so headers maps
like `{"headers": {"x-api-key": "..."}}` are covered."""

_CORRELATION_ID_UNBOUND = "-"


def _timestamper() -> structlog.processors.TimeStamper:
    return structlog.processors.TimeStamper(fmt="iso", utc=True)


def ensure_correlation_id(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Spec 0011 AC-2: `correlation_id` is always present on the rendered event.

    If no middleware or `ExecutionService.execute` has bound a value into
    `structlog.contextvars` (or the caller did not pass one as a kwarg),
    stamp the sentinel `"-"` so downstream log consumers see a stable
    shape even on process boot or in programmatic callers.
    """
    event_dict.setdefault("correlation_id", _CORRELATION_ID_UNBOUND)
    return event_dict


def _redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(key, str) and key.lower() in SENSITIVE_LOG_KEYS:
            out[key] = "<redacted>"
        else:
            out[key] = value
    return out


def redact_sensitive_keys(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Spec 0011 AC-6: replace values of sensitive keys with `"<redacted>"`.

    Recurses one level into nested dicts so a redacted-headers map
    nested under `headers=` is still covered. Deeper nesting is a
    non goal (log payloads should stay flat).
    """
    redacted: dict[str, Any] = {}
    for key, value in event_dict.items():
        if isinstance(key, str) and key.lower() in SENSITIVE_LOG_KEYS:
            redacted[key] = "<redacted>"
        elif isinstance(value, dict):
            redacted[key] = _redact_mapping(value)
        else:
            redacted[key] = value
    return redacted


def safe_render(renderer: Any) -> Any:
    """Spec 0011 AC-10: wrap the final renderer so a serialisation blow up
    never crashes the caller. On failure, write a last resort
    `log.emission_failed` JSON line to stderr and return it instead."""

    def _wrapped(logger: Any, method_name: str, event_dict: dict[str, Any]) -> Any:
        try:
            return renderer(logger, method_name, event_dict)
        except Exception as exc:
            fallback = {
                "event": "log.emission_failed",
                "logger": "app.core.logging",
                "timestamp": _timestamper()(logger, method_name, {}).get("timestamp"),
                "level": "error",
                "correlation_id": event_dict.get("correlation_id", _CORRELATION_ID_UNBOUND),
                "error_type": type(exc).__name__,
                "error_msg": str(exc),
            }
            try:
                serialised = json.dumps(fallback, default=str)
            except Exception:
                serialised = (
                    '{"event":"log.emission_failed","logger":"app.core.logging",'
                    '"level":"error","correlation_id":"-",'
                    f'"error_type":"{type(exc).__name__}"}}'
                )
            sys.stderr.write(serialised + "\n")
            sys.stderr.flush()
            # Belt and braces: dump the original failure trace to stderr too
            # so an operator can diagnose the serialisation failure.
            traceback.print_exc(file=sys.stderr)
            return serialised

    return _wrapped


def _apply_per_module_levels(overrides: dict[str, str]) -> None:
    """Apply spec 0011 AC-5 per module stdlib level overrides.

    `Settings._parse_log_levels` already validated level names, so this
    is a plain apply loop. Called once from `configure_logging`.
    """
    for logger_name, level in overrides.items():
        logging.getLogger(logger_name).setLevel(logging.getLevelName(level))


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging. Idempotent."""
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        _timestamper(),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        ensure_correlation_id,
        redact_sensitive_keys,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    # `LoggerFactory` (stdlib) is required so `get_logger("app.request")`
    # produces a logger whose `.name` the `add_logger_name` processor can
    # read; `PrintLoggerFactory` drops the name at construction time,
    # which is why spec 0011 AC-2's `logger` field was absent before this
    # fix. Routing structlog through the stdlib root handler also lets
    # the per module `LOG_LEVELS` overrides govern structlog events, not
    # just uvicorn/sqlalchemy (AC-5).
    structlog.configure(
        processors=[*shared_processors, safe_render(renderer)],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    # Bridge stdlib logging into structlog format so uvicorn/sqlalchemy lines look consistent.
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(CorrelationIdFilter(uuid_length=32, default_value="-"))
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.getLevelName(settings.log_level))

    # Spec 0011 AC-8: `uvicorn.access` stays at WARNING; `request.completed`
    # emitted by `RequestLoggingMiddleware` is the authoritative per request
    # record. Set this BEFORE per module overrides so an operator who wants
    # the raw access log back can lift the level via `LOG_LEVELS`.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _apply_per_module_levels(settings.log_levels)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


# Spec 0008 AC-18: HTTP header deny list. Any header name (lower cased) in
# this set is replaced with `"<redacted>"` before a request or response log
# event is serialised. Kept alongside spec 0011's `SENSITIVE_LOG_KEYS`
# processor as defence in depth: the middleware redacts at the edge, the
# processor catches anything a caller still manages to bind.
SENSITIVE_REQUEST_HEADERS: frozenset[str] = frozenset(
    {
        "x-api-key",
        "authorization",
    }
)


def redact_headers(headers: dict[str, str] | list[tuple[str, str]]) -> dict[str, str]:
    """Return a shallow copy of `headers` with sensitive values redacted.

    Accepts either a mapping or a list of pairs (ASGI's native shape). Header
    name comparison is case insensitive; the output always lower cases keys
    so downstream log consumers get a stable shape.
    """
    pairs: list[tuple[str, str]] = (
        list(headers.items()) if isinstance(headers, dict) else list(headers)
    )
    out: dict[str, str] = {}
    for name, value in pairs:
        key = name.lower()
        out[key] = "<redacted>" if key in SENSITIVE_REQUEST_HEADERS else value
    return out

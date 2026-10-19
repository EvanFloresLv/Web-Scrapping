"""Structured logging setup.

Per spec 0001: structlog with JSON in deployed envs, pretty renderer in dev.
Correlation ID is bound via asgi-correlation-id middleware (see main.py).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from asgi_correlation_id import CorrelationIdFilter

from app.core.config import Settings


def _timestamper() -> structlog.processors.TimeStamper:
    return structlog.processors.TimeStamper(fmt="iso", utc=True)


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging. Idempotent."""
    # `add_log_level` and `add_logger_name` require a stdlib-backed logger; we use
    # `PrintLoggerFactory` for a lean setup, so we skip those. The level is already
    # encoded by the renderer, and the logger name is passed in via contextvars when
    # callers want it (e.g. `get_logger("app.lifespan")`).
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _timestamper(),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging into structlog format so uvicorn/sqlalchemy lines look consistent.
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(CorrelationIdFilter(uuid_length=32, default_value="-"))
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.getLevelName(settings.log_level))

    # Reduce noise from access logs; uvicorn.error carries real signal.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger

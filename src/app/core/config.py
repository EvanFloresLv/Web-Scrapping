"""Typed application configuration loaded from env vars (and `.env` in dev).

Per spec 0001: pydantic-settings is the single source of truth; validates on startup.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVEL_NAMES: frozenset[str] = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["dev", "test", "staging", "prod"] = Field(default="dev")
    app_name: str = Field(default="scraping-platform")
    api_v1_prefix: str = Field(default="/api/v1")

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_json: bool = Field(default=False, description="JSON logs in deployed envs; pretty in dev.")
    log_levels: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per logger stdlib level overrides as a JSON object, e.g. "
            '`{"app.extraction":"DEBUG","sqlalchemy.engine":"WARNING"}`. '
            "Validated at startup; unknown level names or malformed JSON fail fast "
            "(spec 0011 AC-5)."
        ),
    )

    # Database (async DSN; set via DATABASE_URL in .env)
    database_url: str = Field(
        default="postgresql+asyncpg://scraping:scraping@localhost:55432/scraping",
        description="Async SQLAlchemy DSN for the primary PostgreSQL database.",
    )
    database_echo: bool = Field(default=False)

    # Request limits (spec 0001 pin)
    request_body_max_bytes: int = Field(default=1_048_576, description="1 MB default cap.")

    # HTTP client defaults for the scraper (spec 0001 pin)
    http_connect_timeout_s: float = Field(default=5.0)
    http_read_timeout_s: float = Field(default=25.0)
    http_total_timeout_s: float = Field(default=30.0)

    # Deterministic HTML extraction fetch limits (spec 0005 AC-4).
    extraction_http_connect_timeout_s: float = Field(default=5.0)
    extraction_http_read_timeout_s: float = Field(default=15.0)
    extraction_http_total_timeout_s: float = Field(default=20.0)
    extraction_http_max_body_bytes: int = Field(default=10_000_000)
    extraction_http_max_redirects: int = Field(default=5)
    extraction_http_user_agent: str = Field(
        default="CatalogEnrichmentBot/0.1 (+https://example.com/bot)"
    )

    # Readiness probe per check timeout (spec 0007 AC-10).
    health_ready_check_timeout_s: float = Field(
        default=1.0,
        description="Per check timeout for /health/ready; a check exceeding this is `fail`.",
    )

    # Admin UI foundation (spec 0008).
    admin_api_key: str = Field(
        description=(
            "Single API key the admin UI must present via X-API-Key. "
            "Required at startup; the app refuses to boot without a value "
            "that is non blank and at least 16 characters long (spec 0008 AC-9)."
        ),
    )
    serve_admin_ui: bool = Field(
        default=False,
        description=(
            "When true, FastAPI mounts the built SPA at `/` behind the SPA "
            "router (spec 0008 AC-10). Dev leaves this false so Vite owns "
            "the browser; container builds set it to true."
        ),
    )
    admin_ui_dist_path: str = Field(
        default="frontend/dist",
        description="Filesystem path to the built SPA. Used only when `serve_admin_ui` is true.",
    )

    @field_validator("log_levels", mode="before")
    @classmethod
    def _parse_log_levels(cls, value: Any) -> dict[str, str]:
        """Accept either a dict (already parsed) or a JSON string from env."""
        if value in (None, "", {}):
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"LOG_LEVELS must be a JSON object; got invalid JSON ({exc.msg})."
                ) from exc
        else:
            parsed = value
        if not isinstance(parsed, dict):
            raise ValueError("LOG_LEVELS must be a JSON object mapping logger name to level.")
        result: dict[str, str] = {}
        for key, level in parsed.items():
            if not isinstance(key, str) or not isinstance(level, str):
                raise ValueError("LOG_LEVELS keys and values must be strings.")
            normalised = level.upper()
            if normalised not in _VALID_LOG_LEVEL_NAMES:
                raise ValueError(
                    f"LOG_LEVELS: unknown level {level!r} for logger {key!r}; "
                    f"expected one of {sorted(_VALID_LOG_LEVEL_NAMES)}."
                )
            # Round trip through `getLevelName` to confirm stdlib accepts it.
            numeric = logging.getLevelName(normalised)
            if not isinstance(numeric, int):
                raise ValueError(
                    f"LOG_LEVELS: level {level!r} for logger {key!r} is not a stdlib log level."
                )
            result[key] = normalised
        return result

    @field_validator("admin_api_key")
    @classmethod
    def _validate_admin_api_key(cls, value: str) -> str:
        """Spec 0008: reject empty or whitespace only; require length >= 16."""
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "ADMIN_API_KEY must be set to a non blank value (spec 0008 Security model)."
            )
        if len(stripped) < 16:
            raise ValueError(
                "ADMIN_API_KEY must be at least 16 characters long (spec 0008 Security model)."
            )
        return stripped


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    `Settings()` loads values from `.env` and environment variables (via
    `pydantic-settings`); the required-but-defaultless fields such as
    `admin_api_key` are populated that way, which mypy cannot see.
    """
    return Settings()  # type: ignore[call-arg]

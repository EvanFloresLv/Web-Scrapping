"""Typed application configuration loaded from env vars (and `.env` in dev).

Per spec 0001: pydantic-settings is the single source of truth; validates on startup.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()

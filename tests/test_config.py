"""Settings defaults and spec 0001 pins.

Locks in the request size cap, HTTP client timeouts, api prefix, and env literal
so that drifting them unintentionally fails CI.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_match_spec_pins() -> None:
    s = Settings()
    assert s.api_v1_prefix == "/api/v1"
    assert s.app_name == "scraping-platform"
    assert s.environment == "dev"
    assert s.request_body_max_bytes == 1_048_576  # 1 MB cap pinned by spec 0001
    assert s.http_connect_timeout_s == 5.0
    assert s.http_read_timeout_s == 25.0
    assert s.http_total_timeout_s == 30.0
    assert s.log_level == "INFO"
    assert s.log_json is False


def test_environment_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")  # type: ignore[arg-type]


def test_log_level_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="TRACE")  # type: ignore[arg-type]


def test_environment_accepts_known_values() -> None:
    for env in ("dev", "test", "staging", "prod"):
        s = Settings(environment=env)  # type: ignore[arg-type]
        assert s.environment == env

"""Per process startup gate for the readiness probe (spec 0007 AC-12).

Lives in its own module (not `app.main`) so `app.api.v1.health` can read the
flag without creating a circular import back onto the app factory. The flag
is per worker process; under `uvicorn --workers N` each worker tracks its
own, which is the correct semantic because each worker probes independently.
"""

from __future__ import annotations

from app.core.config import Settings

_startup_complete: bool = False


def assert_required_settings(settings: Settings) -> None:
    """Fail fast on missing or malformed critical settings (spec 0008 Security model).

    Pydantic's `field_validator` on `Settings.admin_api_key` already rejects
    empty, whitespace only, and too short values at `Settings()` time. This
    function belt and braces that at `create_app` time so a mis-wired config
    override cannot slip past (e.g. a test that constructs `Settings` with
    `model_construct`, which skips validators).
    """
    key = (settings.admin_api_key or "").strip()
    if not key or len(key) < 16:
        raise AssertionError(
            "ADMIN_API_KEY must be set to a non blank value of at least 16 "
            "characters (spec 0008 Security model). Set it in `.env` for local "
            "dev or as an environment variable in deployed environments."
        )


def mark_startup_complete() -> None:
    """Flip the gate to `True`. Called from the FastAPI lifespan hook."""
    global _startup_complete
    _startup_complete = True


def is_startup_complete() -> bool:
    """Return the current state of the per worker startup gate."""
    return _startup_complete


def reset_for_tests() -> None:
    """Reset to `False`. Only tests should call this (fresh app per test)."""
    global _startup_complete
    _startup_complete = False


__all__ = [
    "assert_required_settings",
    "is_startup_complete",
    "mark_startup_complete",
    "reset_for_tests",
]

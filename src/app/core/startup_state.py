"""Per process startup gate for the readiness probe (spec 0007 AC-12).

Lives in its own module (not `app.main`) so `app.api.v1.health` can read the
flag without creating a circular import back onto the app factory. The flag
is per worker process; under `uvicorn --workers N` each worker tracks its
own, which is the correct semantic because each worker probes independently.
"""

from __future__ import annotations

_startup_complete: bool = False


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


__all__ = ["is_startup_complete", "mark_startup_complete", "reset_for_tests"]

"""Cached Alembic head for the readiness probe (spec 0007 AC-11).

The expected head is resolved exactly once at import time from the package
relative `alembic.ini`. The readiness check compares this constant against the
`alembic_version` row in Postgres; equal => `ok`, different => `mismatch`,
anything else (unreachable, timeout) => `fail`. Resolving at import keeps
`/health/ready` free of filesystem I/O.

If the ini cannot be read (missing file, parse error), `EXPECTED_HEAD` is
`None` and the probe reports `fail` with a detail naming the ini path. Both
cases are observable, neither crashes app startup.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# Resolve the ini path relative to this file so the lookup works under tests,
# containers, and `uv run` regardless of the process CWD. Layout: this file
# sits at `src/app/core/alembic_head.py`; the ini lives at the repo root
# three levels up.
ALEMBIC_INI_PATH: Path = Path(__file__).resolve().parents[3] / "alembic.ini"


def _resolve_expected_head(ini_path: Path) -> str | None:
    try:
        config = Config(str(ini_path))
        scripts = ScriptDirectory.from_config(config)
        head: str | None = scripts.get_current_head()
    except Exception:
        return None
    return head


EXPECTED_HEAD: str | None = _resolve_expected_head(ALEMBIC_INI_PATH)
"""Alembic head revision expected on a healthy deployment.

Set once per process at module import. `None` means the ini could not be read;
the readiness probe reports `fail` and names the ini path.
"""


__all__ = ["ALEMBIC_INI_PATH", "EXPECTED_HEAD"]

"""Websites domain (spec 0002).

Re-exports the ORM models so Alembic's `target_metadata` import side effect
sees them when `migrations/env.py` imports `app.core.database`.
"""

from __future__ import annotations

from app.domains.websites.models import TargetURL, Website

__all__ = ["TargetURL", "Website"]

"""Authentication primitives for the admin UI (spec 0008)."""

from app.core.auth.api_key import AdminUIUnauthenticated, require_api_key

__all__ = ["AdminUIUnauthenticated", "require_api_key"]

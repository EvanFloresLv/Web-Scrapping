"""SPA router mount (spec 0008 AC-10).

When `SERVE_ADMIN_UI` is true and `frontend/dist/index.html` exists,
FastAPI serves the built admin UI from the same origin as the API, so no
CORS is ever configured. The mount is registered AFTER every API, health,
docs, redoc, and openapi route to guarantee it cannot shadow a backend
route.

Two routes are mounted:

- `GET /assets/*` serves hashed static files from `frontend/dist/assets/`
  via `StaticFiles`.
- `GET /{full_path:path}` is the catch all SPA fallback. For any path
  under a reserved backend prefix it 404s (so a typed JSON client that
  misroutes a call lands on the backend's existing Problem Details 404,
  not SPA HTML). For any other path it inspects the `Accept` header and
  returns `index.html` only when `Accept` contains `text/html`; a JSON
  client receives a 404 instead of SPA HTML.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings
from app.core.errors import _problem_response
from app.core.logging import get_logger

RESERVED_PREFIXES: tuple[str, ...] = (
    "/api/",
    "/health/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/assets/",
)


def mount_spa_router(app: FastAPI, settings: Settings) -> None:
    """Mount the SPA fallthrough router onto `app`, if enabled.

    No op when `SERVE_ADMIN_UI` is false or `index.html` is missing. Called
    from `create_app` as the LAST registration step; any API or docs route
    added later would silently sit behind the catch all and 404.
    """
    log = get_logger("app.spa")
    if not settings.serve_admin_ui:
        return

    dist_root = Path(settings.admin_ui_dist_path)
    if not dist_root.is_absolute():
        dist_root = Path.cwd() / dist_root
    index_html = dist_root / "index.html"
    assets_root = dist_root / "assets"

    if not index_html.is_file():
        log.warning(
            "spa_mount_skipped",
            reason="index.html missing",
            path=str(index_html),
        )
        return

    if assets_root.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_root)),
            name="admin-ui-assets",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str) -> FileResponse:
        """Serve `index.html` for any non reserved GET that accepts HTML."""
        path = "/" + full_path if not full_path.startswith("/") else full_path

        for prefix in RESERVED_PREFIXES:
            if path.startswith(prefix):
                return _problem_response(  # type: ignore[return-value]
                    status_code=status.HTTP_404_NOT_FOUND,
                    title="Not Found",
                    detail=f"No route matches {path!r}.",
                    code="http.404",
                    instance=path,
                )

        accept = request.headers.get("accept", "")
        if "text/html" not in accept:
            return _problem_response(  # type: ignore[return-value]
                status_code=status.HTTP_404_NOT_FOUND,
                title="Not Found",
                detail=f"No route matches {path!r} and the request does not accept HTML.",
                code="http.404",
                instance=path,
            )

        return FileResponse(str(index_html), media_type="text/html")

    log.info("spa_mounted", dist=str(dist_root))

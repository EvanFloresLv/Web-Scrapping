# Verify: Stack & architecture · spec 0001 · updated 2026-10-16

_Steps derived from spec 0001. `/check verify` runs these; `/test` locks the durable ones._

## Commands

- [x] `uv sync --extra dev` → exits 0; installs the pinned dependency set from `pyproject.toml` and writes `uv.lock`. → foundation
- [x] `uv run ruff check src tests` → exits 0 with no violations. → foundation
- [x] `uv run ruff format --check src tests` → exits 0 (already formatted). → foundation
- [x] `uv run mypy src` → exits 0 under `strict = true`. → foundation
- [x] `uv run pytest -q` → 5 tests pass; no warnings except the expected `starlette` deprecation note. → foundation
- [ ] `uv run python -c "from app.main import create_app; app = create_app(); print([r.path for r in app.routes if hasattr(r, 'path')])"` → prints `/api/v1/health/live`, `/api/v1/health/ready`, `/api/v1/openapi.json`, `/api/v1/docs`. → foundation
- [x] `docker compose up -d postgres && docker compose ps` → service healthy, port 5432 bound. → foundation
- [x] `uv run alembic current` → runs without error against the Compose Postgres (no revisions yet; prints nothing). → foundation

## UI / manual (curl against a running uvicorn)

Start: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`

- [x] `curl -s http://127.0.0.1:8000/api/v1/health/live` → `{"status":"ok"}` → foundation
- [x] `curl -i http://127.0.0.1:8000/api/v1/health/live` → response includes an `x-request-id` header (generated when absent). → foundation
- [x] `curl -i -H "X-Request-ID: smoke-abc-123" http://127.0.0.1:8000/api/v1/health/live` → response `x-request-id` equals `smoke-abc-123` (inbound ID preserved, not replaced). → foundation
- [x] `curl -i http://127.0.0.1:8000/api/v1/does-not-exist` → `404`, `Content-Type: application/problem+json`, body contains `"code":"http.404"` and `"correlation_id"`. → foundation
- [x] `curl -i -X POST -H "Content-Type: application/json" --data-binary @<(python -c "print('{\"x\":\"'+ 'a'*2000000 +'\"}')") http://127.0.0.1:8000/api/v1/health/live` → `413`, `Content-Type: application/problem+json`, body contains `"code":"http.413"`. → foundation
- [x] `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/v1/openapi.json` → `200`. → foundation
- [x] `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/v1/docs` → `200` in dev; `404` once `ENVIRONMENT=prod`. → foundation

## Acceptance-criteria coverage

This foundation spec has no feature acceptance criteria (it is a decision spec). The verify steps above cover the scaffold's observable behaviour: health endpoints respond, correlation IDs round-trip, Problem Details is the error contract, the request-size cap enforces the 1 MB pin, lint and types are clean, and the OpenAPI surface is exposed in dev only.

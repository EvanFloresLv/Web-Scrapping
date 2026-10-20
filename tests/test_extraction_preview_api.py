"""Integration tests for `POST /workflows/{id}/versions/{id}/preview` (spec 0005).

Drives the real FastAPI app through `httpx.AsyncClient` against the session
scoped Postgres container; outbound HTTP is intercepted by `respx` on the
same `httpx.AsyncClient` used by `HttpFetcher`. No test hits the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient

API = "/api/v1"
PROBLEM_CT = "application/problem+json"

FIXTURES = Path(__file__).parent / "fixtures" / "extraction"
BASIC_HTML = (FIXTURES / "catalog_basic" / "page.html").read_text(encoding="utf-8")
EXPECTED_BASIC = json.loads(
    (FIXTURES / "catalog_basic" / "expected.json").read_text(encoding="utf-8")
)


def _config(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "container_selector": "article.product",
        "fields": [
            {
                "name": "name",
                "selector": "h2.title",
                "transforms": ["strip"],
                "type": "string",
            },
            {
                "name": "price",
                "selector": "span.price",
                "transforms": ["strip_currency"],
                "type": "string",
            },
            {
                "name": "link",
                "selector": "a.link",
                "transforms": ["attr:href"],
                "type": "url",
            },
        ],
        # Keys match field names so feature 5's publish-time coherence check passes
        # (every field name must be a key in output_schema). An empty value is a
        # placeholder; the extractor's JSON Schema layer accepts any subdoc.
        "output_schema": {"name": {}, "price": {}, "link": {}},
    }
    base.update(overrides)
    return base


async def _setup_website_workflow(
    ac: AsyncClient,
    *,
    config: dict[str, Any] | None = None,
    target_path: str = "/catalog/listing",
) -> tuple[str, str, str]:
    """Register a website + target + draft workflow version. Returns ids and url."""
    r = await ac.post(
        f"{API}/websites",
        json={"host": "example.com", "display_name": "Example"},
    )
    assert r.status_code == 201, r.text
    site = r.json()
    target_url = f"https://example.com{target_path}"
    r = await ac.post(
        f"{API}/websites/{site['id']}/targets",
        json={"url": target_url, "label": "listing"},
    )
    assert r.status_code == 201, r.text
    r = await ac.post(
        f"{API}/websites/{site['id']}/workflows",
        json={"name": "scrape v1", "description": None},
    )
    assert r.status_code == 201, r.text
    workflow = r.json()
    r = await ac.post(
        f"{API}/workflows/{workflow['id']}/versions",
        json={"config": config or _config()},
    )
    assert r.status_code == 201, r.text
    version = r.json()
    return workflow["id"], version["id"], target_url


def _strip_nondeterministic(body: dict[str, Any]) -> dict[str, Any]:
    """Remove duration_ms + any ISO timestamp key before golden compare (AC-19)."""
    stripped = {k: v for k, v in body.items() if k != "duration_ms"}
    return stripped


class TestPreviewCompleted:
    @respx.mock
    async def test_golden_file_catalog_basic(self, api_client: AsyncClient) -> None:
        """covers: AC-1, AC-2, AC-7, AC-8, AC-9, AC-10, AC-11, AC-19."""
        workflow_id, version_id, target_url = await _setup_website_workflow(api_client)
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200,
                text=BASIC_HTML,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            json={"target_url": target_url},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert _strip_nondeterministic(body) == dict(EXPECTED_BASIC)


class TestPreviewFailures:
    @respx.mock
    async def test_container_miss(self, api_client: AsyncClient) -> None:
        """covers: AC-7, AC-14."""
        workflow_id, version_id, target_url = await _setup_website_workflow(
            api_client,
            config=_config(container_selector=".missing"),
        )
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200,
                text=BASIC_HTML,
                headers={"content-type": "text/html"},
            )
        )

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            json={"target_url": target_url},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "failed"
        assert body["error_code"] == "extraction.no_container_match"
        assert body["items"] is None

    @respx.mock
    async def test_http_error(self, api_client: AsyncClient) -> None:
        """covers: AC-4, AC-14."""
        workflow_id, version_id, target_url = await _setup_website_workflow(api_client)
        respx.get(target_url).mock(return_value=httpx.Response(503))

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            json={"target_url": target_url},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "failed"
        assert body["error_code"] == "fetch.http_error"
        assert body["error_details"] == [{"status": 503}]

    @respx.mock
    async def test_unsupported_content_type(self, api_client: AsyncClient) -> None:
        """covers: AC-5, AC-14."""
        workflow_id, version_id, target_url = await _setup_website_workflow(api_client)
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200,
                text="{}",
                headers={"content-type": "application/json"},
            )
        )

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            json={"target_url": target_url},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "failed"
        assert body["error_code"] == "fetch.unsupported_content_type"

    async def test_pagination_unsupported(self, api_client: AsyncClient) -> None:
        """covers: AC-12, AC-14."""
        config = _config(pagination={"next_selector": "a.next", "max_pages": 3})
        workflow_id, version_id, target_url = await _setup_website_workflow(
            api_client, config=config
        )
        # No respx mock: service must short-circuit before fetching.
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            json={"target_url": target_url},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "failed"
        assert body["error_code"] == "extraction.pagination_unsupported"


class TestPreviewLookupFailures:
    async def test_target_not_registered(self, api_client: AsyncClient) -> None:
        """covers: AC-3, AC-14."""
        workflow_id, version_id, _ = await _setup_website_workflow(api_client)
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            json={"target_url": "https://example.com/not/registered"},
        )
        assert r.status_code == 404
        assert r.headers["content-type"].startswith(PROBLEM_CT)
        body = r.json()
        assert body["code"] == "extraction.target_not_registered"

    async def test_workflow_not_found(self, api_client: AsyncClient) -> None:
        """covers: AC-3."""
        r = await api_client.post(
            f"{API}/workflows/00000000-0000-7000-8000-000000000000/versions/00000000-0000-7000-8000-000000000001/preview",
            json={"target_url": "https://example.com/x"},
        )
        assert r.status_code == 404
        assert r.json()["code"] == "workflow.not_found"

    async def test_version_not_found(self, api_client: AsyncClient) -> None:
        """covers: AC-3."""
        workflow_id, _, _ = await _setup_website_workflow(api_client)
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/00000000-0000-7000-8000-000000000099/preview",
            json={"target_url": "https://example.com/catalog/listing"},
        )
        assert r.status_code == 404
        assert r.json()["code"] == "workflow.version_not_found"


class TestPreviewBodyShape:
    async def test_missing_target_url_returns_422(self, api_client: AsyncClient) -> None:
        """covers: AC-2 (invalid_preview_body)."""
        workflow_id, version_id, _ = await _setup_website_workflow(api_client)
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            json={},
        )
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "extraction.invalid_preview_body"
        assert body["errors"]
        assert body["errors"][0]["loc"][0] == "target_url"

    async def test_malformed_json_returns_422(self, api_client: AsyncClient) -> None:
        workflow_id, version_id, _ = await _setup_website_workflow(api_client)
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422
        assert r.json()["code"] == "extraction.invalid_preview_body"


class TestPreviewAgainstDraftVersion:
    @respx.mock
    async def test_draft_version_is_previewable(self, api_client: AsyncClient) -> None:
        """covers: AC-2 (preview works on draft, published, or archived)."""
        workflow_id, version_id, target_url = await _setup_website_workflow(api_client)
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200,
                text=BASIC_HTML,
                headers={"content-type": "text/html"},
            )
        )
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/versions/{version_id}/preview",
            json={"target_url": target_url},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"


# `pytest-asyncio` with `asyncio_mode = auto` picks the `@respx.mock`-decorated
# tests up as async coroutines automatically.
_ = pytest  # keep import if a future test needs parametrize

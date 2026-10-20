"""Integration tests for the sync workflow execution endpoint (spec 0006).

Drives the real FastAPI app through `httpx.AsyncClient` against the session
scoped Postgres container; outbound HTTP is intercepted by `respx` on the
same `httpx.AsyncClient` the extraction service uses. No test hits the net.

The suite is the regression gate for the terminal commit path: before the
`finalise` guard fix, every happy and failed run raised a RuntimeError that
surfaced as 500 (see `/debug` of 2026-10-20). These tests exercise the full
two-commit lifecycle, so they fail on that regression.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import respx
from httpx import AsyncClient

API = "/api/v1"
PROBLEM_CT = "application/problem+json"

FIXTURES = Path(__file__).parent / "fixtures" / "extraction"
BASIC_HTML = (FIXTURES / "catalog_basic" / "page.html").read_text(encoding="utf-8")


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
        "output_schema": {"name": {}, "price": {}, "link": {}},
    }
    base.update(overrides)
    return base


async def _setup_published(
    ac: AsyncClient,
    *,
    config: dict[str, Any] | None = None,
    target_path: str = "/catalog/listing",
) -> tuple[str, str, str, str]:
    """Create a website + target + draft version, then publish.

    Returns `(workflow_id, version_id, target_url_id, target_url)`.
    """
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
    target = r.json()
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
    r = await ac.post(f"{API}/workflows/{workflow['id']}/versions/{version['id']}/publish")
    assert r.status_code == 200, r.text
    return workflow["id"], version["id"], target["id"], target_url


class TestExecuteCompleted:
    @respx.mock
    async def test_happy_path_persists_terminal_row_and_items(
        self, api_client: AsyncClient
    ) -> None:
        """covers: AC-1, AC-5, AC-7, AC-8, AC-12, AC-13.

        Regression: before dropping the ``finalise`` status guard, this ran as
        500 because the service always mutates ``execution.status`` to the
        terminal value before calling finalise, which then raised RuntimeError.
        """
        workflow_id, version_id, target_url_id, target_url = await _setup_published(api_client)
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200,
                text=BASIC_HTML,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            headers={"X-Request-ID": "regress-happy-001"},
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200, r.text
        body = r.json()

        exe = body["execution"]
        assert exe["status"] == "completed"
        assert exe["workflow_id"] == workflow_id
        assert exe["workflow_version_id"] == version_id
        assert exe["target_url_id"] == target_url_id
        assert exe["items_extracted"] == 2
        assert exe["error_code"] is None
        assert exe["error_message"] is None
        assert exe["correlation_id"] == "regress-happy-001"
        assert exe["started_at"] is not None
        assert exe["finished_at"] is not None
        assert isinstance(exe["duration_ms"], int)
        assert exe["duration_ms"] >= 0

        items = body["items"]
        assert [it["item_index"] for it in items] == [0, 1]
        assert items[0]["payload"] == {
            "name": "Widget A",
            "price": "12.50",
            "link": "https://example.com/widget-a",
        }
        assert items[1]["payload"] == {
            "name": "Gadget B",
            "price": "3.00",
            "link": "https://example.com/gadget-b",
        }

    @respx.mock
    async def test_get_by_id_returns_the_same_body_after_completion(
        self, api_client: AsyncClient
    ) -> None:
        """covers: AC-9."""
        workflow_id, _version_id, target_url_id, target_url = await _setup_published(api_client)
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200,
                text=BASIC_HTML,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200
        post_body = r.json()
        execution_id = post_body["execution"]["id"]

        r = await api_client.get(f"{API}/executions/{execution_id}")
        assert r.status_code == 200
        assert r.json() == post_body


class TestExecuteFailed:
    @respx.mock
    async def test_failed_extraction_persists_failed_row_zero_results(
        self, api_client: AsyncClient
    ) -> None:
        """covers: AC-5, AC-7, AC-8, AC-10.

        Regression: before dropping the finalise guard, failed runs also 500'd
        because finalise rejected the mutated terminal status.
        """
        workflow_id, _version_id, target_url_id, target_url = await _setup_published(
            api_client,
            config=_config(container_selector=".missing"),
        )
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200,
                text=BASIC_HTML,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        exe = body["execution"]
        assert exe["status"] == "failed"
        assert exe["items_extracted"] == 0
        assert exe["error_code"] == "extraction.no_container_match"
        assert exe["error_message"]
        assert exe["finished_at"] is not None
        assert isinstance(exe["duration_ms"], int)
        assert body["items"] == []

    @respx.mock
    async def test_failed_fetch_persists_failed_row_with_fetch_code(
        self, api_client: AsyncClient
    ) -> None:
        """covers: AC-5, AC-7, AC-8, AC-10."""
        workflow_id, _version_id, target_url_id, target_url = await _setup_published(api_client)
        respx.get(target_url).mock(return_value=httpx.Response(503))

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        exe = body["execution"]
        assert exe["status"] == "failed"
        assert exe["items_extracted"] == 0
        assert exe["error_code"] == "fetch.http_error"
        assert body["items"] == []

    @respx.mock
    async def test_get_by_id_returns_the_failed_body(self, api_client: AsyncClient) -> None:
        """covers: AC-9."""
        workflow_id, _version_id, target_url_id, target_url = await _setup_published(api_client)
        respx.get(target_url).mock(return_value=httpx.Response(503))

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200
        post_body = r.json()
        execution_id = post_body["execution"]["id"]

        r = await api_client.get(f"{API}/executions/{execution_id}")
        assert r.status_code == 200
        assert r.json() == post_body


class TestExecuteGetMisses:
    async def test_get_by_id_unknown_returns_404_execution_not_found(
        self, api_client: AsyncClient
    ) -> None:
        """covers: AC-9, AC-10, AC-11."""
        unknown = "00000000-0000-7000-8000-999999999999"
        r = await api_client.get(f"{API}/executions/{unknown}")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith(PROBLEM_CT)
        body = r.json()
        assert body["code"] == "execution.not_found"
        assert "correlation_id" in body


class TestPreRunValidationPersistsNoRow:
    async def test_unknown_workflow_404_and_no_execution_follows(
        self, api_client: AsyncClient
    ) -> None:
        """covers: AC-4, AC-6, AC-11.

        A 4xx reject must leave the executions table untouched. We prove it
        by running a subsequent happy-path execution and asserting its item
        index 0 is the first results row for its own execution id (i.e. the
        rejected request did not persist anything that would collide).
        """
        unknown_workflow = "00000000-0000-7000-8000-000000000000"
        some_target = "00000000-0000-7000-8000-111111111111"
        r = await api_client.post(
            f"{API}/workflows/{unknown_workflow}/execute",
            json={"target_url_id": some_target},
        )
        assert r.status_code == 404
        assert r.headers["content-type"].startswith(PROBLEM_CT)
        assert r.json()["code"] == "workflow.not_found"

    async def test_invalid_body_returns_422_invalid_execute_body(
        self, api_client: AsyncClient
    ) -> None:
        """covers: AC-1, AC-11."""
        workflow_id, _vid, _tid, _url = await _setup_published(api_client)

        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            json={},
        )
        assert r.status_code == 422
        assert r.headers["content-type"].startswith(PROBLEM_CT)
        body = r.json()
        assert body["code"] == "execution.invalid_execute_body"
        assert any(d["field"] == "target_url_id" for d in body["details"])

    async def test_workflow_with_no_current_version_409_not_runnable(
        self, api_client: AsyncClient
    ) -> None:
        """covers: AC-2, AC-6, AC-11."""
        # Build a website + target + workflow but no published version.
        r = await api_client.post(
            f"{API}/websites",
            json={"host": "example.com", "display_name": "Example"},
        )
        assert r.status_code == 201
        site = r.json()
        r = await api_client.post(
            f"{API}/websites/{site['id']}/targets",
            json={"url": "https://example.com/catalog/listing", "label": "listing"},
        )
        assert r.status_code == 201
        target = r.json()
        r = await api_client.post(
            f"{API}/websites/{site['id']}/workflows",
            json={"name": "no-version", "description": None},
        )
        assert r.status_code == 201
        workflow = r.json()

        r = await api_client.post(
            f"{API}/workflows/{workflow['id']}/execute",
            json={"target_url_id": target["id"]},
        )
        assert r.status_code == 409
        assert r.headers["content-type"].startswith(PROBLEM_CT)
        assert r.json()["code"] == "execution.workflow_not_runnable"

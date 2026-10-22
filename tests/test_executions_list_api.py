"""Integration tests for `GET /api/v1/executions` (spec 0010 M2).

Drives the real FastAPI app through `httpx.AsyncClient` against the
session scoped Postgres container. Seeds parents and executions via the
ORM directly (fast, no HTTP), then asserts the list endpoint's shape,
filters, cursor pagination, and error paths.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.ids import uuid_v7
from app.domains.executions.cursor import encode_cursor
from app.domains.executions.models import Execution
from app.domains.websites.models import TargetURL, Website
from app.domains.workflows.models import ScrapingWorkflow, WorkflowVersion

API = "/api/v1"
PROBLEM_CT = "application/problem+json"
NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


# --- seed helpers -----------------------------------------------------------


async def _seed(
    pg_engine: AsyncEngine,
    *,
    host: str = "example.com",
    workflow_name: str = "scrape-v1",
) -> tuple[Website, TargetURL, ScrapingWorkflow, WorkflowVersion]:
    factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s, s.begin():
        site = Website(id=uuid_v7(), host=host, display_name=host)
        target = TargetURL(
            id=uuid_v7(),
            website_id=site.id,
            url=f"https://{host}/a",
            label="first",
        )
        workflow = ScrapingWorkflow(
            id=uuid_v7(),
            website_id=site.id,
            name=workflow_name,
            description=None,
        )
        version = WorkflowVersion(
            id=uuid_v7(),
            workflow_id=workflow.id,
            version_number=1,
            status="published",
            config={
                "container_selector": "body",
                "fields": [{"name": "x", "selector": "body", "type": "string"}],
                "output_schema": {"x": {}},
            },
            published_at=NOW,
        )
        s.add_all([site, target, workflow, version])
        await s.flush()
        workflow.current_version_id = version.id
    return site, target, workflow, version


async def _seed_execution(
    pg_engine: AsyncEngine,
    *,
    version_id: UUID,
    target_id: UUID,
    created_at: datetime,
    status: str = "completed",
    correlation_id: str = "cid-x",
) -> UUID:
    factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)
    row_id = uuid_v7()
    async with factory() as s, s.begin():
        s.add(
            Execution(
                id=row_id,
                workflow_version_id=version_id,
                target_url_id=target_id,
                status=status,
                started_at=created_at,
                finished_at=created_at,
                duration_ms=1,
                items_extracted=0,
                correlation_id=correlation_id,
                created_at=created_at,
            )
        )
        await s.flush()
        await s.execute(
            text("UPDATE executions SET created_at = :c WHERE id = :i"),
            {"c": created_at, "i": row_id},
        )
    return row_id


# --- happy path -------------------------------------------------------------


class TestListHappyPath:
    @pytest.mark.asyncio
    async def test_returns_items_and_null_cursor_when_page_not_full(
        self,
        api_client: AsyncClient,
        pg_engine: AsyncEngine,
    ) -> None:
        # covers: AC-1
        _, target, workflow, version = await _seed(pg_engine)
        row_id = await _seed_execution(
            pg_engine, version_id=version.id, target_id=target.id, created_at=NOW
        )
        r = await api_client.get(f"{API}/executions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["next_cursor"] is None
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["id"] == str(row_id)
        assert item["workflow_id"] == str(workflow.id)
        assert item["workflow_version_id"] == str(version.id)
        assert item["status"] == "completed"
        assert item["correlation_id"] == "cid-x"

    @pytest.mark.asyncio
    async def test_cursor_pagination_walks_full_set(
        self,
        api_client: AsyncClient,
        pg_engine: AsyncEngine,
    ) -> None:
        # covers: AC-1, AC-2
        _, target, _, version = await _seed(pg_engine)
        ids: list[UUID] = []
        for i in range(5):
            ids.append(
                await _seed_execution(
                    pg_engine,
                    version_id=version.id,
                    target_id=target.id,
                    created_at=NOW + timedelta(seconds=5 - i),
                )
            )
        # Newest first: ids[0] is newest (NOW + 5s), ids[-1] is oldest.
        r = await api_client.get(f"{API}/executions?page_size=25")
        body = r.json()
        assert [item["id"] for item in body["items"]] == [str(i) for i in ids]
        assert body["next_cursor"] is None

        # Force paginate with page_size=25 (min allowed).
        r1 = await api_client.get(f"{API}/executions?page_size=25")
        r2 = await api_client.get(f"{API}/executions?page_size=25")
        assert r1.status_code == 200
        assert r2.status_code == 200

    @pytest.mark.asyncio
    async def test_next_cursor_walks_when_page_is_full(
        self,
        api_client: AsyncClient,
        pg_engine: AsyncEngine,
    ) -> None:
        # covers: AC-2
        _, target, _, version = await _seed(pg_engine)
        for i in range(26):  # 26 rows, min page_size is 25
            await _seed_execution(
                pg_engine,
                version_id=version.id,
                target_id=target.id,
                created_at=NOW + timedelta(seconds=100 - i),
            )
        r1 = await api_client.get(f"{API}/executions?page_size=25")
        assert r1.status_code == 200
        body1 = r1.json()
        assert len(body1["items"]) == 25
        assert body1["next_cursor"] is not None

        r2 = await api_client.get(f"{API}/executions?page_size=25&cursor={body1['next_cursor']}")
        assert r2.status_code == 200
        body2 = r2.json()
        assert len(body2["items"]) == 1
        assert body2["next_cursor"] is None


# --- filters ----------------------------------------------------------------


class TestFilters:
    @pytest.mark.asyncio
    async def test_status_filter(
        self,
        api_client: AsyncClient,
        pg_engine: AsyncEngine,
    ) -> None:
        # covers: AC-3
        _, target, _, version = await _seed(pg_engine)
        completed = await _seed_execution(
            pg_engine,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW,
            status="completed",
        )
        await _seed_execution(
            pg_engine,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW,
            status="failed",
        )
        r = await api_client.get(f"{API}/executions?status=completed")
        assert r.status_code == 200
        body = r.json()
        assert [item["id"] for item in body["items"]] == [str(completed)]

    @pytest.mark.asyncio
    async def test_correlation_id_filter(
        self,
        api_client: AsyncClient,
        pg_engine: AsyncEngine,
    ) -> None:
        # covers: AC-3, AC-6
        _, target, _, version = await _seed(pg_engine)
        hit = await _seed_execution(
            pg_engine,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW,
            correlation_id="ticket-7",
        )
        await _seed_execution(
            pg_engine,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW,
            correlation_id="other",
        )
        r = await api_client.get(f"{API}/executions?correlation_id=ticket-7")
        assert r.status_code == 200
        body = r.json()
        assert [item["id"] for item in body["items"]] == [str(hit)]

    @pytest.mark.asyncio
    async def test_website_id_filter_scopes_through_workflow(
        self,
        api_client: AsyncClient,
        pg_engine: AsyncEngine,
    ) -> None:
        # covers: AC-5
        site_a, target_a, _, version_a = await _seed(pg_engine)
        _, target_b, _, version_b = await _seed(
            pg_engine, host="other.example", workflow_name="other-wf"
        )
        kept = await _seed_execution(
            pg_engine, version_id=version_a.id, target_id=target_a.id, created_at=NOW
        )
        await _seed_execution(
            pg_engine, version_id=version_b.id, target_id=target_b.id, created_at=NOW
        )
        r = await api_client.get(f"{API}/executions?website_id={site_a.id}")
        assert r.status_code == 200
        body = r.json()
        assert [item["id"] for item in body["items"]] == [str(kept)]

    @pytest.mark.asyncio
    async def test_with_deleted_hides_soft_deleted_workflow_executions(
        self,
        api_client: AsyncClient,
        pg_engine: AsyncEngine,
    ) -> None:
        # covers: AC-4
        _, target, workflow, version = await _seed(pg_engine)
        row = await _seed_execution(
            pg_engine, version_id=version.id, target_id=target.id, created_at=NOW
        )
        # Soft delete the workflow out of band.
        factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s, s.begin():
            await s.execute(
                text("UPDATE scraping_workflows SET deleted_at = :t WHERE id = :i"),
                {"t": NOW, "i": workflow.id},
            )
        hidden = await api_client.get(f"{API}/executions")
        assert hidden.json()["items"] == []
        shown = await api_client.get(f"{API}/executions?with_deleted=true")
        assert [item["id"] for item in shown.json()["items"]] == [str(row)]


# --- error paths ------------------------------------------------------------


class TestValidationErrors:
    @pytest.mark.asyncio
    async def test_malformed_cursor_returns_400_invalid_cursor(
        self,
        api_client: AsyncClient,
    ) -> None:
        # covers: AC-2
        r = await api_client.get(f"{API}/executions?cursor=not!base64@@")
        assert r.status_code == 400
        assert r.headers["content-type"].startswith(PROBLEM_CT)
        body = r.json()
        assert body["code"] == "execution.invalid_cursor"

    @pytest.mark.asyncio
    async def test_window_inverted_returns_422(
        self,
        api_client: AsyncClient,
    ) -> None:
        # covers: AC-3
        r = await api_client.get(
            f"{API}/executions?created_from=2026-10-21T00:00:00Z&created_to=2026-10-20T00:00:00Z"
        )
        assert r.status_code == 422
        assert r.headers["content-type"].startswith(PROBLEM_CT)
        body = r.json()
        assert body["code"] == "execution.invalid_list_query"

    @pytest.mark.asyncio
    async def test_unknown_status_returns_422(
        self,
        api_client: AsyncClient,
    ) -> None:
        # covers: AC-3
        r = await api_client.get(f"{API}/executions?status=garbage")
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "execution.invalid_list_query"

    @pytest.mark.asyncio
    async def test_page_size_out_of_range_returns_422(
        self,
        api_client: AsyncClient,
    ) -> None:
        # covers: AC-2
        r = await api_client.get(f"{API}/executions?page_size=999")
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_cursor_round_trips_through_the_endpoint(
        self,
        api_client: AsyncClient,
        pg_engine: AsyncEngine,
    ) -> None:
        # covers: AC-2
        _, target, _, version = await _seed(pg_engine)
        newer = await _seed_execution(
            pg_engine, version_id=version.id, target_id=target.id, created_at=NOW
        )
        _ = await _seed_execution(
            pg_engine,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW - timedelta(hours=1),
        )
        cursor = encode_cursor(NOW, newer)
        r = await api_client.get(f"{API}/executions?cursor={cursor}")
        assert r.status_code == 200
        body = r.json()
        # Older row only.
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] != str(newer)

"""`SqlAlchemyExecutionRepository.list_page` (spec 0010 AC-1..AC-6).

Covers the keyset ordering, cursor pagination, every filter, the
`with_deleted` join gate, the `website_id` join through
`workflow_versions -> scraping_workflows`, and the point lookup on
`correlation_id` (backed by the new `ix_executions_correlation_id`
index this feature adds).

The tests seed rows via the ORM directly (fast, no HTTP), then call
the repository method through the request scoped `db_session`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid_v7
from app.domains.executions.cursor import Cursor
from app.domains.executions.enums import ExecutionStatus
from app.domains.executions.models import Execution
from app.domains.executions.repository import (
    ExecutionListFilters,
    SqlAlchemyExecutionRepository,
)
from app.domains.websites.models import TargetURL, Website
from app.domains.workflows.models import ScrapingWorkflow, WorkflowVersion

NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


# --- fixtures ---------------------------------------------------------------


async def _seed_parents(
    db_session: AsyncSession,
    *,
    host: str = "example.com",
    workflow_name: str = "scrape-v1",
) -> tuple[Website, TargetURL, ScrapingWorkflow, WorkflowVersion]:
    site = Website(
        id=uuid_v7(),
        host=host,
        display_name=host,
    )
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
    db_session.add_all([site, target, workflow, version])
    await db_session.flush()
    workflow.current_version_id = version.id
    await db_session.flush()
    return site, target, workflow, version


async def _seed_execution(
    db_session: AsyncSession,
    *,
    version_id: UUID,
    target_id: UUID,
    created_at: datetime,
    status: str = "completed",
    correlation_id: str = "cid-x",
) -> Execution:
    ex = Execution(
        id=uuid_v7(),
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
    db_session.add(ex)
    await db_session.flush()
    # Force the created_at override (ORM default was server now()).
    await db_session.execute(
        text("UPDATE executions SET created_at = :c WHERE id = :i"),
        {"c": created_at, "i": ex.id},
    )
    await db_session.refresh(ex)
    return ex


# --- tests ------------------------------------------------------------------


class TestOrderingAndPagination:
    @pytest.mark.asyncio
    async def test_returns_newest_first_with_total_order_on_id(
        self, db_session: AsyncSession
    ) -> None:
        # covers: AC-1
        _, target, _, version = await _seed_parents(db_session)
        a = await _seed_execution(
            db_session, version_id=version.id, target_id=target.id, created_at=NOW
        )
        b = await _seed_execution(
            db_session, version_id=version.id, target_id=target.id, created_at=NOW
        )
        c = await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW + timedelta(seconds=1),
        )
        repo = SqlAlchemyExecutionRepository(db_session)
        rows = await repo.list_page(ExecutionListFilters(), cursor=None, page_size=10)
        ids = [r.id for r in rows]
        assert ids[0] == c.id  # newest first
        # Tie on created_at between a and b is broken by id DESC.
        assert ids[1:] == sorted([a.id, b.id], reverse=True)

    @pytest.mark.asyncio
    async def test_cursor_restricts_to_strictly_older_rows(self, db_session: AsyncSession) -> None:
        # covers: AC-2
        _, target, _, version = await _seed_parents(db_session)
        older = await _seed_execution(
            db_session, version_id=version.id, target_id=target.id, created_at=NOW
        )
        newer = await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW + timedelta(seconds=60),
        )
        repo = SqlAlchemyExecutionRepository(db_session)
        cursor = Cursor(created_at=newer.created_at, id=newer.id)
        page = await repo.list_page(ExecutionListFilters(), cursor=cursor, page_size=10)
        assert [r.id for r in page] == [older.id]

    @pytest.mark.asyncio
    async def test_page_size_caps_result(self, db_session: AsyncSession) -> None:
        # covers: AC-1, AC-2
        _, target, _, version = await _seed_parents(db_session)
        for i in range(5):
            await _seed_execution(
                db_session,
                version_id=version.id,
                target_id=target.id,
                created_at=NOW - timedelta(seconds=i),
            )
        repo = SqlAlchemyExecutionRepository(db_session)
        page = await repo.list_page(ExecutionListFilters(), cursor=None, page_size=2)
        assert len(page) == 2


class TestFilters:
    @pytest.mark.asyncio
    async def test_status_filter_selects_matching_rows_only(self, db_session: AsyncSession) -> None:
        # covers: AC-3
        _, target, _, version = await _seed_parents(db_session)
        passed = await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW,
            status="completed",
        )
        await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW,
            status="failed",
        )
        repo = SqlAlchemyExecutionRepository(db_session)
        filters = ExecutionListFilters(status=ExecutionStatus.COMPLETED)
        page = await repo.list_page(filters, cursor=None, page_size=10)
        assert [r.id for r in page] == [passed.id]

    @pytest.mark.asyncio
    async def test_correlation_id_point_lookup(self, db_session: AsyncSession) -> None:
        # covers: AC-6
        _, target, _, version = await _seed_parents(db_session)
        hit = await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW,
            correlation_id="support-ticket-123",
        )
        await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW,
            correlation_id="other-run",
        )
        repo = SqlAlchemyExecutionRepository(db_session)
        page = await repo.list_page(
            ExecutionListFilters(correlation_id="support-ticket-123"),
            cursor=None,
            page_size=10,
        )
        assert [r.id for r in page] == [hit.id]

    @pytest.mark.asyncio
    async def test_created_from_and_to_window(self, db_session: AsyncSession) -> None:
        # covers: AC-3
        _, target, _, version = await _seed_parents(db_session)
        inside = await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW - timedelta(hours=1),
        )
        await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW - timedelta(days=10),
        )
        await _seed_execution(
            db_session,
            version_id=version.id,
            target_id=target.id,
            created_at=NOW + timedelta(hours=1),
        )
        repo = SqlAlchemyExecutionRepository(db_session)
        page = await repo.list_page(
            ExecutionListFilters(
                created_from=NOW - timedelta(hours=2),
                created_to=NOW,
            ),
            cursor=None,
            page_size=10,
        )
        assert [r.id for r in page] == [inside.id]

    @pytest.mark.asyncio
    async def test_workflow_id_filter_scopes_to_that_workflow(
        self, db_session: AsyncSession
    ) -> None:
        # covers: AC-3, AC-5
        _, target_a, workflow_a, version_a = await _seed_parents(db_session)
        _, _, _, version_b = await _seed_parents(
            db_session, host="other.example", workflow_name="other-wf"
        )
        kept = await _seed_execution(
            db_session, version_id=version_a.id, target_id=target_a.id, created_at=NOW
        )
        await _seed_execution(
            db_session,
            version_id=version_b.id,
            target_id=target_a.id,
            created_at=NOW,
        )
        repo = SqlAlchemyExecutionRepository(db_session)
        page = await repo.list_page(
            ExecutionListFilters(workflow_id=workflow_a.id),
            cursor=None,
            page_size=10,
        )
        assert [r.id for r in page] == [kept.id]

    @pytest.mark.asyncio
    async def test_website_id_filter_joins_through_workflow(self, db_session: AsyncSession) -> None:
        # covers: AC-5
        site_a, target_a, _, version_a = await _seed_parents(db_session)
        _, target_b, _, version_b = await _seed_parents(
            db_session, host="other.example", workflow_name="other-wf"
        )
        kept = await _seed_execution(
            db_session, version_id=version_a.id, target_id=target_a.id, created_at=NOW
        )
        await _seed_execution(
            db_session, version_id=version_b.id, target_id=target_b.id, created_at=NOW
        )
        repo = SqlAlchemyExecutionRepository(db_session)
        page = await repo.list_page(
            ExecutionListFilters(website_id=site_a.id),
            cursor=None,
            page_size=10,
        )
        assert [r.id for r in page] == [kept.id]


class TestWithDeleted:
    @pytest.mark.asyncio
    async def test_hides_soft_deleted_workflow_executions_by_default(
        self, db_session: AsyncSession
    ) -> None:
        # covers: AC-4
        _, target, workflow, version = await _seed_parents(db_session)
        row = await _seed_execution(
            db_session, version_id=version.id, target_id=target.id, created_at=NOW
        )
        workflow.deleted_at = NOW
        await db_session.flush()
        repo = SqlAlchemyExecutionRepository(db_session)
        hidden = await repo.list_page(
            ExecutionListFilters(with_deleted=False), cursor=None, page_size=10
        )
        assert hidden == []
        shown = await repo.list_page(
            ExecutionListFilters(with_deleted=True), cursor=None, page_size=10
        )
        assert [r.id for r in shown] == [row.id]

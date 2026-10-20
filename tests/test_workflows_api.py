"""Integration tests for workflow configuration & versioning (spec 0004).

Drives the real FastAPI app via `httpx.AsyncClient` against the session scoped
Postgres container. Each test is tagged with the `AC-N` from the spec it
exercises so the suite traces back to the contract.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

API = "/api/v1"
PROBLEM_CT = "application/problem+json"


def _config(**overrides: Any) -> dict[str, Any]:
    """Return a valid `WorkflowConfig` payload (AC-7)."""
    base: dict[str, Any] = {
        "container_selector": "div.product",
        "fields": [
            {"name": "title", "selector": "h2", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
        ],
        "output_schema": {"title": "string", "price": "string"},
    }
    base.update(overrides)
    return base


async def _create_website(ac: AsyncClient, host: str = "example.com") -> dict[str, Any]:
    r = await ac.post(f"{API}/websites", json={"host": host, "display_name": "X"})
    assert r.status_code == 201, r.text
    return r.json()


async def _create_workflow(
    ac: AsyncClient, website_id: str, name: str = "scrape v1"
) -> dict[str, Any]:
    r = await ac.post(
        f"{API}/websites/{website_id}/workflows",
        json={"name": name, "description": "d"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _create_draft(
    ac: AsyncClient, workflow_id: str, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    r = await ac.post(
        f"{API}/workflows/{workflow_id}/versions",
        json={"config": config or _config()},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- AC-1 / AC-2 : create workflow ---------------------------------


class TestCreateWorkflow:
    async def test_create_returns_201_with_defaults(self, api_client: AsyncClient) -> None:
        """covers: AC-1 (defaults active, current_version_id=null)."""
        site = await _create_website(api_client)
        r = await api_client.post(
            f"{API}/websites/{site['id']}/workflows",
            json={"name": "scrape v1", "description": "d"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["website_id"] == site["id"]
        assert body["status"] == "active"
        assert body["current_version_id"] is None
        assert body["name"] == "scrape v1"

    async def test_duplicate_name_returns_409(self, api_client: AsyncClient) -> None:
        """covers: AC-2 (name conflict)."""
        site = await _create_website(api_client)
        await _create_workflow(api_client, site["id"], name="dup")
        r = await api_client.post(
            f"{API}/websites/{site['id']}/workflows",
            json={"name": "dup"},
        )
        assert r.status_code == 409
        assert r.headers["content-type"] == PROBLEM_CT
        assert r.json()["code"] == "workflow.name_conflict"

    async def test_unknown_website_returns_404(self, api_client: AsyncClient) -> None:
        """covers: AC-2 (missing website)."""
        r = await api_client.post(
            f"{API}/websites/00000000-0000-0000-0000-000000000000/workflows",
            json={"name": "x"},
        )
        assert r.status_code == 404
        assert r.json()["code"] == "website.not_found"

    async def test_soft_deleted_website_returns_404(self, api_client: AsyncClient) -> None:
        """covers: AC-2 (soft deleted website is invisible)."""
        site = await _create_website(api_client, host="gone.example")
        assert (await api_client.delete(f"{API}/websites/{site['id']}")).status_code == 204
        r = await api_client.post(f"{API}/websites/{site['id']}/workflows", json={"name": "x"})
        assert r.status_code == 404

    async def test_re_register_after_soft_delete(self, api_client: AsyncClient) -> None:
        """covers: AC-2, AC-5 (partial unique excludes soft deleted)."""
        site = await _create_website(api_client)
        first = await _create_workflow(api_client, site["id"], name="again")
        assert (await api_client.delete(f"{API}/workflows/{first['id']}")).status_code == 204
        r = await api_client.post(f"{API}/websites/{site['id']}/workflows", json={"name": "again"})
        assert r.status_code == 201
        assert r.json()["id"] != first["id"]


# ---------- AC-3 : list workflows / get workflow --------------------------


class TestListWorkflow:
    async def test_list_filters_soft_deleted(self, api_client: AsyncClient) -> None:
        """covers: AC-3, AC-16 (default hides soft deleted)."""
        site = await _create_website(api_client)
        kept = await _create_workflow(api_client, site["id"], name="keep")
        gone = await _create_workflow(api_client, site["id"], name="gone")
        await api_client.delete(f"{API}/workflows/{gone['id']}")

        r = await api_client.get(f"{API}/websites/{site['id']}/workflows")
        assert r.status_code == 200
        ids = [w["id"] for w in r.json()["items"]]
        assert kept["id"] in ids
        assert gone["id"] not in ids

        r2 = await api_client.get(
            f"{API}/websites/{site['id']}/workflows", params={"with_deleted": "true"}
        )
        ids2 = [w["id"] for w in r2.json()["items"]]
        assert gone["id"] in ids2

    async def test_pagination_envelope(self, api_client: AsyncClient) -> None:
        """covers: AC-3 (page / page_size / total)."""
        site = await _create_website(api_client)
        for i in range(5):
            await _create_workflow(api_client, site["id"], name=f"w{i}")
        r = await api_client.get(
            f"{API}/websites/{site['id']}/workflows",
            params={"page": 1, "page_size": 2},
        )
        body = r.json()
        assert body["total"] == 5
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) == 2

    async def test_invalid_pagination_returns_422(self, api_client: AsyncClient) -> None:
        """covers: AC-3 (bounds)."""
        site = await _create_website(api_client)
        r = await api_client.get(
            f"{API}/websites/{site['id']}/workflows", params={"page_size": 500}
        )
        assert r.status_code == 422
        assert r.json()["code"] == "workflow.invalid_pagination"

    async def test_unknown_workflow_returns_404(self, api_client: AsyncClient) -> None:
        """covers: AC-3 (get by id)."""
        r = await api_client.get(f"{API}/workflows/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404
        assert r.json()["code"] == "workflow.not_found"


# ---------- AC-4 : PATCH workflow -----------------------------------------


class TestPatchWorkflow:
    async def test_patch_name_updates(self, api_client: AsyncClient) -> None:
        """covers: AC-4 (name is patchable)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"], name="old")
        r = await api_client.patch(f"{API}/workflows/{w['id']}", json={"name": "new"})
        assert r.status_code == 200
        assert r.json()["name"] == "new"

    async def test_empty_patch_is_noop_200(self, api_client: AsyncClient) -> None:
        """covers: AC-4 (empty body)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        r = await api_client.patch(f"{API}/workflows/{w['id']}", json={})
        assert r.status_code == 200
        assert r.json()["id"] == w["id"]

    async def test_immutable_field_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-4 (website_id not patchable)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        r = await api_client.patch(
            f"{API}/workflows/{w['id']}",
            json={"website_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert r.status_code == 422
        assert r.json()["code"] == "workflow.immutable_field"

    async def test_name_collision_409(self, api_client: AsyncClient) -> None:
        """covers: AC-4 (409 when renaming collides)."""
        site = await _create_website(api_client)
        await _create_workflow(api_client, site["id"], name="taken")
        w = await _create_workflow(api_client, site["id"], name="free")
        r = await api_client.patch(f"{API}/workflows/{w['id']}", json={"name": "taken"})
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.name_conflict"


# ---------- AC-5 : DELETE workflow (idempotent, in flight gate) ------------


class TestDeleteWorkflow:
    async def test_delete_is_idempotent(self, api_client: AsyncClient) -> None:
        """covers: AC-5."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        assert (await api_client.delete(f"{API}/workflows/{w['id']}")).status_code == 204
        assert (await api_client.delete(f"{API}/workflows/{w['id']}")).status_code == 204

    async def test_in_flight_execution_blocks_delete(
        self, api_client: AsyncClient, pg_engine: Any
    ) -> None:
        """covers: AC-5 (running execution refuses delete)."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.domains.executions.models import Execution

        site = await _create_website(api_client)
        workflow = await _create_workflow(api_client, site["id"])
        version = await _create_draft(api_client, workflow["id"])
        tr = await api_client.post(
            f"{API}/websites/{site['id']}/targets",
            json={"url": "https://example.com/p/1", "label": "p1"},
        )
        assert tr.status_code == 201, tr.text
        target_id = tr.json()["id"]

        factory = async_sessionmaker(bind=pg_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            session.add(
                Execution(
                    workflow_version_id=version["id"],
                    target_url_id=target_id,
                    status="running",
                    correlation_id="corr-test",
                )
            )
            await session.commit()

        r = await api_client.delete(f"{API}/workflows/{workflow['id']}")
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.has_in_flight_executions"


# ---------- AC-6 / AC-7 : create version + coherence ----------------------


class TestCreateVersion:
    async def test_create_draft_assigns_version_number_1(self, api_client: AsyncClient) -> None:
        """covers: AC-6 (defaults, auto number)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions", json={"config": _config()})
        assert r.status_code == 201
        body = r.json()
        assert body["version_number"] == 1
        assert body["status"] == "draft"
        assert body["workflow_id"] == w["id"]

    async def test_second_draft_gets_version_number_2(self, api_client: AsyncClient) -> None:
        """covers: AC-6 (monotonic)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        await _create_draft(api_client, w["id"])
        v2 = await _create_draft(api_client, w["id"])
        assert v2["version_number"] == 2

    async def test_inactive_workflow_refuses_version(self, api_client: AsyncClient) -> None:
        """covers: AC-6 (409 inactive)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        await api_client.patch(f"{API}/workflows/{w['id']}", json={"status": "inactive"})
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions", json={"config": _config()})
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.inactive"

    async def test_missing_workflow_404(self, api_client: AsyncClient) -> None:
        """covers: AC-6 (unknown parent)."""
        r = await api_client.post(
            f"{API}/workflows/00000000-0000-0000-0000-000000000000/versions",
            json={"config": _config()},
        )
        assert r.status_code == 404
        assert r.json()["code"] == "workflow.not_found"

    async def test_config_shape_violation_422(self, api_client: AsyncClient) -> None:
        """covers: AC-7 (Pydantic shape error)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        bad = _config()
        bad.pop("container_selector")
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions", json={"config": bad})
        assert r.status_code == 422

    async def test_duplicate_field_names_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-7 (field name uniqueness)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        bad = _config(
            fields=[
                {"name": "title", "selector": "h2", "type": "text"},
                {"name": "title", "selector": "h3", "type": "text"},
            ],
            output_schema={"title": "string"},
        )
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions", json={"config": bad})
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "workflow.validation_error"
        assert any("title" in d["loc"] for d in body["errors"])

    async def test_output_schema_coverage_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-7 (every field name must be in output_schema)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        bad = _config(output_schema={"title": "string"})  # missing `price`
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions", json={"config": bad})
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "workflow.validation_error"
        assert any("price" in d["loc"] for d in body["errors"])


# ---------- AC-8 : list versions / get version ----------------------------


class TestListVersion:
    async def test_list_ordered_by_number_desc(self, api_client: AsyncClient) -> None:
        """covers: AC-8 (DESC order)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        await _create_draft(api_client, w["id"])
        await _create_draft(api_client, w["id"])
        r = await api_client.get(f"{API}/workflows/{w['id']}/versions")
        assert r.status_code == 200
        numbers = [v["version_number"] for v in r.json()["items"]]
        assert numbers == sorted(numbers, reverse=True)

    async def test_get_version_wrong_workflow_404(self, api_client: AsyncClient) -> None:
        """covers: AC-8 (mismatched parent -> 404 not 400)."""
        site = await _create_website(api_client)
        a = await _create_workflow(api_client, site["id"], name="a")
        b = await _create_workflow(api_client, site["id"], name="b")
        va = await _create_draft(api_client, a["id"])
        r = await api_client.get(f"{API}/workflows/{b['id']}/versions/{va['id']}")
        assert r.status_code == 404
        assert r.json()["code"] == "workflow.version_not_found"


# ---------- AC-9 : PATCH draft --------------------------------------------


class TestPatchVersion:
    async def test_patch_draft_replaces_config(self, api_client: AsyncClient) -> None:
        """covers: AC-9."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        new_cfg = _config(container_selector="div.other")
        r = await api_client.patch(
            f"{API}/workflows/{w['id']}/versions/{v['id']}",
            json={"config": new_cfg},
        )
        assert r.status_code == 200
        assert r.json()["config"]["container_selector"] == "div.other"

    async def test_patch_unknown_field_422(self, api_client: AsyncClient) -> None:
        """covers: AC-9 (immutable field)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        r = await api_client.patch(
            f"{API}/workflows/{w['id']}/versions/{v['id']}",
            json={"status": "published"},
        )
        assert r.status_code == 422
        assert r.json()["code"] == "workflow.immutable_field"

    async def test_patch_published_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-9 (non draft -> 409)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        pub = await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/publish")
        assert pub.status_code == 200
        r = await api_client.patch(
            f"{API}/workflows/{w['id']}/versions/{v['id']}",
            json={"config": _config()},
        )
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.version_not_draft"


# ---------- AC-10 : DELETE draft -----------------------------------------


class TestDeleteDraft:
    async def test_delete_draft_204(self, api_client: AsyncClient) -> None:
        """covers: AC-10."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        r = await api_client.delete(f"{API}/workflows/{w['id']}/versions/{v['id']}")
        assert r.status_code == 204
        r2 = await api_client.get(f"{API}/workflows/{w['id']}/versions/{v['id']}")
        assert r2.status_code == 404

    async def test_delete_published_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-10 (409 on non draft)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/publish")
        r = await api_client.delete(f"{API}/workflows/{w['id']}/versions/{v['id']}")
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.version_not_draft"


# ---------- AC-11 : publish --------------------------------------------


class TestPublish:
    async def test_first_publish_sets_current_version(self, api_client: AsyncClient) -> None:
        """covers: AC-11 (first publish promotes draft, swaps current pointer)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/publish")
        assert r.status_code == 200
        assert r.json()["status"] == "published"
        assert r.json()["published_at"] is not None

        w_after = (await api_client.get(f"{API}/workflows/{w['id']}")).json()
        assert w_after["current_version_id"] == v["id"]

    async def test_second_publish_archives_previous(self, api_client: AsyncClient) -> None:
        """covers: AC-11 (publish auto archives previous current)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v1 = await _create_draft(api_client, w["id"])
        v2 = await _create_draft(api_client, w["id"])
        await api_client.post(f"{API}/workflows/{w['id']}/versions/{v1['id']}/publish")
        await api_client.post(f"{API}/workflows/{w['id']}/versions/{v2['id']}/publish")

        prev = (await api_client.get(f"{API}/workflows/{w['id']}/versions/{v1['id']}")).json()
        assert prev["status"] == "archived"
        assert prev["archived_at"] is not None

        w_after = (await api_client.get(f"{API}/workflows/{w['id']}")).json()
        assert w_after["current_version_id"] == v2["id"]

    async def test_publish_non_draft_409(self, api_client: AsyncClient) -> None:
        """covers: AC-11 (non draft target)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/publish")
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/publish")
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.version_conflict"

    async def test_publish_on_inactive_workflow_409(self, api_client: AsyncClient) -> None:
        """covers: AC-11 (inactive)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        await api_client.patch(f"{API}/workflows/{w['id']}", json={"status": "inactive"})
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/publish")
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.inactive"


# ---------- AC-12 : archive --------------------------------------------


class TestArchive:
    async def test_archive_non_current_published(self, api_client: AsyncClient) -> None:
        """covers: AC-12 (archive previously published, non current)."""
        # Publish v1, publish v2 (auto archives v1). Then try to archive v1
        # again: it's already archived → version_not_published.
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v1 = await _create_draft(api_client, w["id"])
        v2 = await _create_draft(api_client, w["id"])
        await api_client.post(f"{API}/workflows/{w['id']}/versions/{v1['id']}/publish")
        await api_client.post(f"{API}/workflows/{w['id']}/versions/{v2['id']}/publish")

        r = await api_client.post(f"{API}/workflows/{w['id']}/versions/{v1['id']}/archive")
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.version_not_published"

    async def test_archive_current_version_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-12 (cannot archive the current published version)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/publish")
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/archive")
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.version_is_current"

    async def test_archive_draft_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-12 (draft is not published)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        v = await _create_draft(api_client, w["id"])
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions/{v['id']}/archive")
        assert r.status_code == 409
        assert r.json()["code"] == "workflow.version_not_published"


# ---------- AC-13 : Problem Details envelope ------------------------------


class TestProblemDetails:
    async def test_404_has_problem_envelope(self, api_client: AsyncClient) -> None:
        """covers: AC-13."""
        r = await api_client.get(
            f"{API}/workflows/00000000-0000-0000-0000-000000000000",
            headers={"X-Request-ID": "corr-wf"},
        )
        assert r.status_code == 404
        assert r.headers["content-type"] == PROBLEM_CT
        body = r.json()
        assert body["code"] == "workflow.not_found"
        assert body["correlation_id"] == "corr-wf"
        assert body["title"]
        assert body["status"] == 404

    async def test_422_has_details_array(self, api_client: AsyncClient) -> None:
        """covers: AC-13 (details[] on validation errors)."""
        site = await _create_website(api_client)
        w = await _create_workflow(api_client, site["id"])
        bad = _config(
            fields=[
                {"name": "x", "selector": "a", "type": "t"},
                {"name": "x", "selector": "b", "type": "t"},
            ],
            output_schema={"x": "string"},
        )
        r = await api_client.post(f"{API}/workflows/{w['id']}/versions", json={"config": bad})
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "workflow.validation_error"
        assert isinstance(body["errors"], list)
        assert body["errors"]

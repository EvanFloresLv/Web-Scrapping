"""Integration tests for the website & target registration API (spec 0002).

Hits the real FastAPI app via `httpx.AsyncClient`, backed by a session-scoped
Postgres (`pg_engine`) with a per-test TRUNCATE. Each test is tagged with the
`AC-N` from the spec it exercises so the suite traces back to the contract.
"""

from __future__ import annotations

from httpx import AsyncClient

API = "/api/v1"
PROBLEM_CT = "application/problem+json"


async def _create_website(
    api_client: AsyncClient, *, host: str = "example.com", display_name: str = "Example"
) -> dict:
    r = await api_client.post(f"{API}/websites", json={"host": host, "display_name": display_name})
    assert r.status_code == 201, r.text
    return r.json()


async def _create_target(
    api_client: AsyncClient,
    website_id: str,
    *,
    url: str = "https://example.com/p/1",
    label: str = "P1",
) -> dict:
    r = await api_client.post(
        f"{API}/websites/{website_id}/targets",
        json={"url": url, "label": label},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- AC-1 + AC-3: create website, canonical host ---------------------


class TestCreateWebsite:
    async def test_create_website_canonicalizes_host(self, api_client: AsyncClient) -> None:
        """covers: AC-1, AC-3 (host lowercase, default port stripped)."""
        r = await api_client.post(
            f"{API}/websites",
            json={"host": "Example.COM:443", "display_name": "Example"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["host"] == "example.com"
        assert body["display_name"] == "Example"
        assert body["status"] == "active"
        assert body["id"]
        # created_at/updated_at are UTC with trailing Z
        assert body["created_at"].endswith("Z")
        assert body["updated_at"].endswith("Z")

    async def test_create_website_idn_punycoded(self, api_client: AsyncClient) -> None:
        """covers: AC-3 (IDN host -> punycode)."""
        body = await _create_website(api_client, host="Bücher.example", display_name="IDN")
        assert body["host"] == "xn--bcher-kva.example"

    async def test_duplicate_website_returns_409(self, api_client: AsyncClient) -> None:
        """covers: AC-4 (409 duplicate_website with existing_id + canonical_host)."""
        first = await _create_website(api_client)
        r = await api_client.post(
            f"{API}/websites", json={"host": "EXAMPLE.com", "display_name": "Dup"}
        )
        assert r.status_code == 409
        assert r.headers["content-type"] == PROBLEM_CT
        body = r.json()
        assert body["code"] == "website.duplicate"
        meta = body["errors"][0]["meta"]
        assert meta["existing_id"] == first["id"]
        assert meta["canonical_host"] == "example.com"

    async def test_display_name_empty_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-7 (field validation)."""
        r = await api_client.post(
            f"{API}/websites", json={"host": "example.com", "display_name": ""}
        )
        assert r.status_code == 422

    async def test_oversize_body_rejected_with_413(self, api_client: AsyncClient) -> None:
        """covers: AC-7 (1 MB middleware cap)."""
        big = "x" * 1_050_000
        r = await api_client.post(
            f"{API}/websites",
            json={"host": "example.com", "display_name": big},
        )
        assert r.status_code == 413


# ---------- AC-2 + AC-3: create target, canonical url -----------------------


class TestCreateTarget:
    async def test_create_target_canonicalizes_url(self, api_client: AsyncClient) -> None:
        """covers: AC-2, AC-3 (url lowercase, default port stripped, fragment dropped)."""
        site = await _create_website(api_client)
        r = await api_client.post(
            f"{API}/websites/{site['id']}/targets",
            json={"url": "HTTPS://Example.COM:443/p/1#top", "label": "P1"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["url"] == "https://example.com/p/1"
        assert body["website_id"] == site["id"]
        assert body["status"] == "active"

    async def test_duplicate_target_returns_409(self, api_client: AsyncClient) -> None:
        """covers: AC-4 (409 duplicate_target with existing_id + canonical_url)."""
        site = await _create_website(api_client)
        first = await _create_target(api_client, site["id"])
        r = await api_client.post(
            f"{API}/websites/{site['id']}/targets",
            json={"url": "https://example.com/p/1", "label": "Dup"},
        )
        assert r.status_code == 409
        assert r.headers["content-type"] == PROBLEM_CT
        body = r.json()
        assert body["code"] == "website.target_duplicate"
        meta = body["errors"][0]["meta"]
        assert meta["existing_id"] == first["id"]
        assert meta["canonical_url"] == "https://example.com/p/1"

    async def test_host_mismatch_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-5 (host_mismatch 422)."""
        site = await _create_website(api_client)
        r = await api_client.post(
            f"{API}/websites/{site['id']}/targets",
            json={"url": "https://other.com/x", "label": "X"},
        )
        assert r.status_code == 422
        assert r.json()["code"] == "website.host_mismatch"

    async def test_inactive_parent_rejects_target(self, api_client: AsyncClient) -> None:
        """covers: AC-6 (parent inactive -> 422 website_inactive)."""
        site = await _create_website(api_client)
        patch = await api_client.patch(f"{API}/websites/{site['id']}", json={"status": "inactive"})
        assert patch.status_code == 200
        r = await api_client.post(
            f"{API}/websites/{site['id']}/targets",
            json={"url": "https://example.com/p/9", "label": "x"},
        )
        assert r.status_code == 422
        assert r.json()["code"] == "website.inactive"

    async def test_soft_deleted_parent_returns_404(self, api_client: AsyncClient) -> None:
        """covers: AC-6 (parent soft-deleted -> 404)."""
        site = await _create_website(api_client, host="gone.example", display_name="Gone")
        assert (await api_client.delete(f"{API}/websites/{site['id']}")).status_code == 204
        r = await api_client.post(
            f"{API}/websites/{site['id']}/targets",
            json={"url": "https://gone.example/x", "label": "x"},
        )
        assert r.status_code == 404

    async def test_bad_scheme_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-7 (http/https only)."""
        site = await _create_website(api_client)
        r = await api_client.post(
            f"{API}/websites/{site['id']}/targets",
            json={"url": "ftp://example.com/x", "label": "x"},
        )
        assert r.status_code == 422


# ---------- AC-8: listing + status filter + pagination ----------------------


class TestList:
    async def test_default_status_excludes_inactive(self, api_client: AsyncClient) -> None:
        """covers: AC-8 (default status=active excludes inactive rows)."""
        active = await _create_website(api_client, host="a.example", display_name="A")
        inactive = await _create_website(api_client, host="b.example", display_name="B")
        await api_client.patch(f"{API}/websites/{inactive['id']}", json={"status": "inactive"})

        r = await api_client.get(f"{API}/websites")
        assert r.status_code == 200
        ids = [w["id"] for w in r.json()["items"]]
        assert active["id"] in ids
        assert inactive["id"] not in ids

    async def test_status_all_includes_inactive(self, api_client: AsyncClient) -> None:
        """covers: AC-8 (?status=all includes inactive, excludes soft-deleted)."""
        active = await _create_website(api_client, host="a.example", display_name="A")
        inactive = await _create_website(api_client, host="b.example", display_name="B")
        deleted = await _create_website(api_client, host="c.example", display_name="C")
        await api_client.patch(f"{API}/websites/{inactive['id']}", json={"status": "inactive"})
        await api_client.delete(f"{API}/websites/{deleted['id']}")

        r = await api_client.get(f"{API}/websites", params={"status": "all"})
        ids = [w["id"] for w in r.json()["items"]]
        assert active["id"] in ids
        assert inactive["id"] in ids
        assert deleted["id"] not in ids

    async def test_targets_listed_under_inactive_parent(self, api_client: AsyncClient) -> None:
        """covers: AC-8 (inactive parent still lists its targets)."""
        site = await _create_website(api_client)
        await _create_target(api_client, site["id"])
        await api_client.patch(f"{API}/websites/{site['id']}", json={"status": "inactive"})
        r = await api_client.get(f"{API}/websites/{site['id']}/targets")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    async def test_targets_under_soft_deleted_parent_404(self, api_client: AsyncClient) -> None:
        """covers: AC-8 (soft-deleted parent -> 404 on target list)."""
        site = await _create_website(api_client, host="gone.example", display_name="Gone")
        await api_client.delete(f"{API}/websites/{site['id']}")
        r = await api_client.get(f"{API}/websites/{site['id']}/targets")
        assert r.status_code == 404

    async def test_pagination_page_size_over_200_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-7 (page_size max 200)."""
        r = await api_client.get(f"{API}/websites", params={"page_size": 201})
        assert r.status_code == 422


# ---------- AC-9: single reads ---------------------------------------------


class TestRead:
    async def test_unknown_website_id_404(self, api_client: AsyncClient) -> None:
        """covers: AC-9."""
        r = await api_client.get(f"{API}/websites/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    async def test_unknown_target_id_404(self, api_client: AsyncClient) -> None:
        """covers: AC-9."""
        r = await api_client.get(f"{API}/targets/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404


# ---------- AC-10: PATCH mutable + immutable --------------------------------


class TestPatch:
    async def test_patch_website_immutable_host_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-10 (host immutable)."""
        site = await _create_website(api_client)
        r = await api_client.patch(f"{API}/websites/{site['id']}", json={"host": "other.com"})
        assert r.status_code == 422
        assert r.json()["code"] == "website.immutable_field"

    async def test_patch_target_immutable_url_rejected(self, api_client: AsyncClient) -> None:
        """covers: AC-10 (url immutable)."""
        site = await _create_website(api_client)
        target = await _create_target(api_client, site["id"])
        r = await api_client.patch(
            f"{API}/targets/{target['id']}", json={"url": "https://example.com/other"}
        )
        assert r.status_code == 422
        assert r.json()["code"] == "website.immutable_field"

    async def test_empty_body_patch_is_200(self, api_client: AsyncClient) -> None:
        """covers: AC-10 (empty-body PATCH returns current resource)."""
        site = await _create_website(api_client)
        r = await api_client.patch(f"{API}/websites/{site['id']}", json={})
        assert r.status_code == 200
        assert r.json()["id"] == site["id"]

    async def test_patch_display_name_updates(self, api_client: AsyncClient) -> None:
        """covers: AC-10 (display_name mutable)."""
        site = await _create_website(api_client)
        r = await api_client.patch(
            f"{API}/websites/{site['id']}", json={"display_name": "New Name"}
        )
        assert r.status_code == 200
        assert r.json()["display_name"] == "New Name"


# ---------- AC-11 + AC-12: DELETE cascade, idempotent, re-register ----------


class TestDelete:
    async def test_delete_cascades_to_targets(self, api_client: AsyncClient) -> None:
        """covers: AC-11 (cascade soft-delete)."""
        site = await _create_website(api_client)
        target = await _create_target(api_client, site["id"])
        assert (await api_client.delete(f"{API}/websites/{site['id']}")).status_code == 204
        assert (await api_client.get(f"{API}/targets/{target['id']}")).status_code == 404
        assert (await api_client.get(f"{API}/websites/{site['id']}")).status_code == 404

    async def test_delete_is_idempotent(self, api_client: AsyncClient) -> None:
        """covers: AC-11 (second DELETE still 204)."""
        site = await _create_website(api_client)
        assert (await api_client.delete(f"{API}/websites/{site['id']}")).status_code == 204
        assert (await api_client.delete(f"{API}/websites/{site['id']}")).status_code == 204

    async def test_re_register_after_delete(self, api_client: AsyncClient) -> None:
        """covers: AC-12 (partial unique index allows re-registration)."""
        first = await _create_website(api_client)
        await api_client.delete(f"{API}/websites/{first['id']}")
        r = await api_client.post(
            f"{API}/websites",
            json={"host": "example.com", "display_name": "Reborn"},
        )
        assert r.status_code == 201
        assert r.json()["id"] != first["id"]


# ---------- AC-13: Problem Details envelope on every 4xx --------------------


class TestProblemDetails:
    async def test_duplicate_response_is_problem_json(self, api_client: AsyncClient) -> None:
        """covers: AC-13 (content-type + stable code + correlation_id)."""
        await _create_website(api_client)
        r = await api_client.post(
            f"{API}/websites",
            json={"host": "example.com", "display_name": "d"},
            headers={"X-Request-ID": "corr-xyz"},
        )
        assert r.status_code == 409
        assert r.headers["content-type"] == PROBLEM_CT
        body = r.json()
        assert body["code"] == "website.duplicate"
        assert body["correlation_id"] == "corr-xyz"

    async def test_404_envelope_shape(self, api_client: AsyncClient) -> None:
        """covers: AC-13 (404 responses are Problem Details too)."""
        r = await api_client.get(f"{API}/websites/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404
        assert r.headers["content-type"] == PROBLEM_CT
        body = r.json()
        assert body["code"] == "website.not_found"
        assert "correlation_id" in body

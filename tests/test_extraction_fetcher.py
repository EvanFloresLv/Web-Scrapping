"""Unit tests for `HttpFetcher` (spec 0005 AC-4, AC-5).

Drives the fetcher through an `httpx.AsyncClient` with `respx` stubs so
every branch of fetch failure maps to the expected `FetchErrorCode`.
No test hits the network.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx

from app.core.errors.execution_codes import FetchErrorCode
from app.domains.extraction.errors import FetchError
from app.domains.extraction.fetcher import FetcherLimits, HttpFetcher

URL = "https://example.com/catalog"


def _limits(**overrides: object) -> FetcherLimits:
    base: dict[str, object] = {
        "connect_timeout_s": 5.0,
        "read_timeout_s": 15.0,
        "total_timeout_s": 20.0,
        "max_body_bytes": 1_000_000,
        "max_redirects": 5,
        "user_agent": "CatalogEnrichmentBot/0.1 (+https://example.com/bot)",
    }
    base.update(overrides)
    return FetcherLimits(**base)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as c:
        yield c


class TestHappyPath:
    @respx.mock
    async def test_returns_body_and_charset_from_header(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content=b"<html><body>ok</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )
        outcome = await HttpFetcher(client, _limits()).fetch(URL)
        assert outcome.body == b"<html><body>ok</body></html>"
        assert outcome.charset == "utf-8"
        assert outcome.final_url == URL

    @respx.mock
    async def test_accepts_xhtml(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content=b"<x/>",
                headers={"content-type": "application/xhtml+xml"},
            )
        )
        outcome = await HttpFetcher(client, _limits()).fetch(URL)
        assert outcome.body == b"<x/>"

    @respx.mock
    async def test_content_type_is_case_insensitive_with_params(
        self, client: httpx.AsyncClient
    ) -> None:
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content=b"<p>x</p>",
                headers={"content-type": 'TEXT/HTML; charset="ISO-8859-1"'},
            )
        )
        outcome = await HttpFetcher(client, _limits()).fetch(URL)
        assert outcome.charset == "ISO-8859-1"

    @respx.mock
    async def test_sniffs_charset_when_header_omits_it(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content="<html><body>áéíóú</body></html>".encode(),
                headers={"content-type": "text/html"},
            )
        )
        outcome = await HttpFetcher(client, _limits()).fetch(URL)
        assert outcome.charset is not None


class TestHttpStatusErrors:  # AC-4
    @respx.mock
    async def test_503_maps_to_http_error(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(return_value=httpx.Response(503))
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits()).fetch(URL)
        assert exc.value.code == FetchErrorCode.HTTP_ERROR
        assert exc.value.details == [{"status": 503}]

    @respx.mock
    async def test_404_maps_to_http_error(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(return_value=httpx.Response(404))
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits()).fetch(URL)
        assert exc.value.code == FetchErrorCode.HTTP_ERROR


class TestContentTypeGate:  # AC-5
    @respx.mock
    async def test_json_rejected(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content=b"{}",
                headers={"content-type": "application/json"},
            )
        )
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits()).fetch(URL)
        assert exc.value.code == FetchErrorCode.UNSUPPORTED_CONTENT_TYPE
        assert exc.value.details == [{"content_type": "application/json"}]

    @respx.mock
    async def test_missing_content_type_rejected(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, content=b"<p/>"))
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits()).fetch(URL)
        assert exc.value.code == FetchErrorCode.UNSUPPORTED_CONTENT_TYPE


class TestBodyCap:  # AC-4
    @respx.mock
    async def test_body_past_cap_raises(self, client: httpx.AsyncClient) -> None:
        payload = b"<p>" + b"x" * 2048 + b"</p>"
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content=payload,
                headers={"content-type": "text/html"},
            )
        )
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits(max_body_bytes=1024)).fetch(URL)
        assert exc.value.code == FetchErrorCode.BODY_TOO_LARGE
        assert exc.value.details == [{"max_bytes": 1024}]

    @respx.mock
    async def test_body_exactly_at_cap_succeeds(self, client: httpx.AsyncClient) -> None:
        payload = b"<p>" + b"x" * 1017 + b"</p>"
        assert len(payload) == 1024
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content=payload,
                headers={"content-type": "text/html"},
            )
        )
        outcome = await HttpFetcher(client, _limits(max_body_bytes=1024)).fetch(URL)
        assert outcome.body == payload


class TestTransportErrors:  # AC-4
    @respx.mock
    async def test_timeout_maps_to_fetch_timeout(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits()).fetch(URL)
        assert exc.value.code == FetchErrorCode.TIMEOUT

    @respx.mock
    async def test_connect_error_maps_to_connection_error(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(side_effect=httpx.ConnectError("dns"))
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits()).fetch(URL)
        assert exc.value.code == FetchErrorCode.CONNECTION_ERROR

    @respx.mock
    async def test_too_many_redirects(self, client: httpx.AsyncClient) -> None:
        respx.get(URL).mock(side_effect=httpx.TooManyRedirects("loop"))
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits(max_redirects=5)).fetch(URL)
        assert exc.value.code == FetchErrorCode.TOO_MANY_REDIRECTS
        assert exc.value.details == [{"max_redirects": 5}]

    @respx.mock
    async def test_generic_request_error_is_connection_error(
        self, client: httpx.AsyncClient
    ) -> None:
        respx.get(URL).mock(side_effect=httpx.RequestError("boom"))
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits()).fetch(URL)
        assert exc.value.code == FetchErrorCode.CONNECTION_ERROR

    async def test_invalid_url_maps_to_invalid_url(self, client: httpx.AsyncClient) -> None:
        with pytest.raises(FetchError) as exc:
            await HttpFetcher(client, _limits()).fetch("http://[::bad::")
        assert exc.value.code == FetchErrorCode.INVALID_URL

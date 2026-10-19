"""HTTP fetcher for deterministic extraction (spec 0005, AC-4, AC-5).

One shared `httpx.AsyncClient` is built once in the app lifespan and reused
for every call; per request client creation is forbidden (connection pool
is the whole point). The fetcher streams the response body and aborts past
`max_body_bytes`, enforces the configured timeouts, and only accepts
`text/html` or `application/xhtml+xml` responses.

Every failure is mapped to a `FetchErrorCode` via `FetchError`; the
service layer catches that and shapes the terminal `ExtractionResult`.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.errors.execution_codes import FetchErrorCode
from app.domains.extraction.errors import FetchError
from app.domains.extraction.schemas import FetchOutcome

_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"text/html", "application/xhtml+xml"})
_CHARSET_SNIFF_WINDOW = 10_000


def _parse_content_type(header: str | None) -> tuple[str, str | None]:
    """Return `(media_type_lower, charset_or_none)` from a Content-Type header."""
    if not header:
        return "", None
    main, _, params = header.partition(";")
    media_type = main.strip().lower()
    charset: str | None = None
    for part in params.split(";"):
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "charset":
            charset = value.strip().strip('"') or None
            break
    return media_type, charset


@dataclass(frozen=True, slots=True)
class FetcherLimits:
    """Per fetch limits read from pydantic-settings at startup (AC-4)."""

    connect_timeout_s: float
    read_timeout_s: float
    total_timeout_s: float
    max_body_bytes: int
    max_redirects: int
    user_agent: str


class HttpFetcher:
    """Fetches a URL through the shared `httpx.AsyncClient` (AC-4).

    The client is passed in rather than created here so a FastAPI dependency
    (`get_http_client`) can override it in tests via `app.dependency_overrides`
    without touching module level state.
    """

    def __init__(self, client: httpx.AsyncClient, limits: FetcherLimits) -> None:
        self._client = client
        self._limits = limits

    async def fetch(self, url: str) -> FetchOutcome:
        """Fetch `url` and return a `FetchOutcome` or raise `FetchError`.

        Streams the body so the byte cap is enforced before the whole page
        is in memory (AC-4). The content type is checked before the body is
        read (AC-5); a wrong type short circuits to
        `fetch.unsupported_content_type`.
        """
        timeout = httpx.Timeout(
            self._limits.total_timeout_s,
            connect=self._limits.connect_timeout_s,
            read=self._limits.read_timeout_s,
        )
        headers = {"User-Agent": self._limits.user_agent}

        try:
            async with self._client.stream(
                "GET",
                url,
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise FetchError(
                        FetchErrorCode.HTTP_ERROR,
                        f"HTTP {response.status_code}",
                        details=[{"status": response.status_code}],
                    )

                media_type, charset = _parse_content_type(response.headers.get("content-type"))
                if media_type not in _ALLOWED_CONTENT_TYPES:
                    raise FetchError(
                        FetchErrorCode.UNSUPPORTED_CONTENT_TYPE,
                        f"content type {media_type!r} not supported",
                        details=[{"content_type": media_type or ""}],
                    )

                cap = self._limits.max_body_bytes
                chunks: list[bytes] = []
                received = 0
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    if received > cap:
                        raise FetchError(
                            FetchErrorCode.BODY_TOO_LARGE,
                            f"response body exceeds {cap} bytes",
                            details=[{"max_bytes": cap}],
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
                final_url = str(response.url)
        except FetchError:
            raise
        except httpx.TooManyRedirects as exc:
            raise FetchError(
                FetchErrorCode.TOO_MANY_REDIRECTS,
                f"redirect cap of {self._limits.max_redirects} exceeded",
                details=[{"max_redirects": self._limits.max_redirects}],
            ) from exc
        except httpx.TimeoutException as exc:
            raise FetchError(
                FetchErrorCode.TIMEOUT,
                "HTTP request timed out",
            ) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise FetchError(
                FetchErrorCode.CONNECTION_ERROR,
                f"could not connect: {exc}",
            ) from exc
        except httpx.InvalidURL as exc:
            raise FetchError(
                FetchErrorCode.INVALID_URL,
                f"invalid URL: {exc}",
            ) from exc
        except httpx.RequestError as exc:
            raise FetchError(
                FetchErrorCode.CONNECTION_ERROR,
                f"transport error: {exc}",
            ) from exc

        if charset is None:
            charset = _sniff_charset(body[:_CHARSET_SNIFF_WINDOW])

        return FetchOutcome(body=body, charset=charset, final_url=final_url)


def _sniff_charset(sample: bytes) -> str | None:
    """Best effort charset autodetect used when Content-Type omits one.

    Uses `charset_normalizer` when available (a transitive httpx dep); falls
    back to UTF 8 at the parser layer when neither header nor sniff returns
    a hit.
    """
    try:
        from charset_normalizer import from_bytes
    except ImportError:  # pragma: no cover - dep is transitive via httpx
        return None
    match = from_bytes(sample).best()
    if match is None:
        return None
    return str(match.encoding)

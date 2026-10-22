"""Spec 0011 contract tests for structured logging & correlation.

Exercises the processor chain, correlation propagation, redaction, no body
policy, access log policy, and the canonical catalogue coverage for
`request`, `execution`, and `extraction` domains.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import (
    SENSITIVE_LOG_KEYS,
    configure_logging,
    ensure_correlation_id,
    get_logger,
    redact_sensitive_keys,
    safe_render,
)

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "extraction"
BASIC_HTML = (FIXTURES / "catalog_basic" / "page.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-2 Required fields on every event
# ---------------------------------------------------------------------------


def test_ac2_ensure_correlation_id_stamps_sentinel_when_unbound() -> None:
    out = ensure_correlation_id(None, "info", {"event": "x"})
    assert out["correlation_id"] == "-"


def test_ac2_ensure_correlation_id_preserves_bound_value() -> None:
    out = ensure_correlation_id(None, "info", {"event": "x", "correlation_id": "abc"})
    assert out["correlation_id"] == "abc"


def test_ac2_rendered_event_carries_all_required_fields(test_settings: Settings) -> None:
    """Spec 0011 AC-2: every rendered event JSON MUST carry `event`, `logger`,
    `timestamp`, `level`, `correlation_id`. Regression for the gap /check
    verify caught: `logger` was absent on every live event because the
    processor set omitted `add_logger_name` and the factory dropped the
    name passed to `get_logger(...)`.
    """
    sink = io.StringIO()
    settings = test_settings.model_copy(update={"log_json": True})
    configure_logging(settings)
    sink_handler = logging.StreamHandler(sink)
    sink_handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    root.handlers = [sink_handler]
    try:
        get_logger("app.request").info("request.completed", status=200)
    finally:
        root.handlers = original_handlers
    event = json.loads(sink.getvalue().strip().splitlines()[-1])
    for field in ("event", "logger", "timestamp", "level", "correlation_id"):
        assert field in event, f"required field {field!r} missing from rendered event {event!r}"
    assert event["logger"] == "app.request"
    assert event["event"] == "request.completed"
    assert event["level"] == "info"
    assert event["correlation_id"] == "-"


# ---------------------------------------------------------------------------
# AC-5 Per module log levels
# ---------------------------------------------------------------------------


def test_ac5_log_levels_rejects_unknown_level() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(  # type: ignore[call-arg]
            admin_api_key="x" * 20,
            log_levels='{"app.extraction": "LOUD"}',
        )
    assert "unknown level" in str(exc.value).lower()


def test_ac5_log_levels_rejects_malformed_json() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(  # type: ignore[call-arg]
            admin_api_key="x" * 20,
            log_levels="{not json",
        )
    assert "invalid json" in str(exc.value).lower()


def test_ac5_log_levels_accepts_valid_map_and_applies(test_settings: Settings) -> None:
    settings = Settings(  # type: ignore[call-arg]
        environment="test",
        log_json=False,
        admin_api_key=test_settings.admin_api_key,
        log_levels='{"app.extraction": "DEBUG", "sqlalchemy.engine": "WARNING"}',
    )
    assert settings.log_levels == {"app.extraction": "DEBUG", "sqlalchemy.engine": "WARNING"}
    configure_logging(settings)
    assert logging.getLogger("app.extraction").level == logging.DEBUG
    assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING


# ---------------------------------------------------------------------------
# AC-6 Sensitive key redaction
# ---------------------------------------------------------------------------


def test_ac6_redact_sensitive_keys_top_level_and_nested() -> None:
    out = redact_sensitive_keys(
        None,
        "info",
        {
            "event": "x",
            "api_key": "secret",
            "X-API-Key": "also-secret",
            "safe": "ok",
            "headers": {"authorization": "Bearer t", "content-type": "application/json"},
        },
    )
    assert out["api_key"] == "<redacted>"
    assert out["X-API-Key"] == "<redacted>"
    assert out["safe"] == "ok"
    assert out["headers"]["authorization"] == "<redacted>"
    assert out["headers"]["content-type"] == "application/json"


def test_ac6_sensitive_log_keys_set_covers_contract() -> None:
    assert {
        "api_key",
        "authorization",
        "password",
        "token",
        "cookie",
        "set-cookie",
        "x-api-key",
    } <= SENSITIVE_LOG_KEYS


def test_ac6_rendered_output_only_sees_redacted(test_settings: Settings) -> None:
    """End to end: configure a JSON sink via the stdlib root handler and
    assert the raw output never contains a sensitive value."""
    sink = io.StringIO()
    settings = test_settings.model_copy(update={"log_json": True})
    configure_logging(settings)

    # Replace the stderr handler installed by `configure_logging` with one
    # that writes to our StringIO sink so we can grep the rendered JSON.
    sink_handler = logging.StreamHandler(sink)
    sink_handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    root.handlers = [sink_handler]
    try:
        log = get_logger("app.test")
        log.info("api_key.created", api_key="super-secret-value", user="alice")
    finally:
        root.handlers = original_handlers

    rendered = sink.getvalue()
    assert "super-secret-value" not in rendered
    assert '"api_key": "<redacted>"' in rendered or '"api_key":"<redacted>"' in rendered
    assert '"logger": "app.test"' in rendered or '"logger":"app.test"' in rendered


# ---------------------------------------------------------------------------
# AC-10 Logging failure safety
# ---------------------------------------------------------------------------


def test_ac10_safe_render_swallows_exceptions_and_emits_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(_logger: Any, _method: str, _event: dict[str, Any]) -> str:
        raise TypeError("boom")

    wrapped = safe_render(broken)
    result = wrapped(None, "info", {"event": "x", "correlation_id": "abc"})
    assert isinstance(result, str)

    err = capsys.readouterr().err
    assert "log.emission_failed" in err
    assert "TypeError" in err


# ---------------------------------------------------------------------------
# AC-11 Fixture ergonomics + AC-3/AC-4 correlation propagation
# ---------------------------------------------------------------------------


async def _setup_published(ac: AsyncClient) -> tuple[str, str, str, str]:
    r = await ac.post(f"{API}/websites", json={"host": "example.com", "display_name": "Example"})
    assert r.status_code == 201, r.text
    site = r.json()
    target_url = "https://example.com/catalog/listing"
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
    config = {
        "container_selector": "article.product",
        "fields": [
            {"name": "name", "selector": "h2.title", "transforms": ["strip"], "type": "string"},
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
    r = await ac.post(f"{API}/workflows/{workflow['id']}/versions", json={"config": config})
    assert r.status_code == 201, r.text
    version = r.json()
    r = await ac.post(f"{API}/workflows/{workflow['id']}/versions/{version['id']}/publish")
    assert r.status_code == 200, r.text
    return workflow["id"], version["id"], target["id"], target_url


class TestCorrelationPropagationHappy:
    @respx.mock
    async def test_request_execution_extraction_share_correlation_id(
        self,
        api_client: AsyncClient,
        caplog_structlog: list[dict[str, Any]],
    ) -> None:
        """AC-3 + AC-4 + AC-9: one HTTP request → execution → extraction;
        every emitted event in the chain carries the same `correlation_id`
        bound by middleware, without per call kwargs."""
        workflow_id, _version_id, target_url_id, target_url = await _setup_published(api_client)
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200, text=BASIC_HTML, headers={"content-type": "text/html; charset=utf-8"}
            )
        )

        correlation_id = "contract-happy-001"
        caplog_structlog.clear()
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            headers={"X-Request-ID": correlation_id},
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200, r.text

        by_event: dict[str, list[dict[str, Any]]] = {}
        for entry in caplog_structlog:
            by_event.setdefault(str(entry.get("event", "")), []).append(entry)

        # Every logged event here must carry the request's correlation_id.
        for events in by_event.values():
            for entry in events:
                assert entry.get("correlation_id") == correlation_id, entry

        # AC-9: canonical catalogue coverage for execution + extraction.
        assert "execution.started" in by_event
        assert "execution.completed" in by_event
        assert "extraction.fetch_started" in by_event
        assert "extraction.fetch_completed" in by_event
        assert "extraction.parse_completed" in by_event
        assert "extraction.extract_completed" in by_event
        assert "extraction.validate_completed" in by_event
        assert "request.completed" in by_event

        # AC-4: execution events auto bind `execution_id` via contextvars.
        for name in ("execution.started", "execution.completed"):
            assert "execution_id" in by_event[name][0], by_event[name][0]
        # The extraction events emitted inside execute inherit it too.
        for extraction_event in ("extraction.fetch_started", "extraction.extract_completed"):
            assert "execution_id" in by_event[extraction_event][0], by_event[extraction_event][0]


class TestCorrelationPropagationError:
    @respx.mock
    async def test_execution_failed_shares_correlation_id(
        self,
        api_client: AsyncClient,
        caplog_structlog: list[dict[str, Any]],
    ) -> None:
        """AC-11 error path for `execution` + `extraction`: upstream 503
        yields `extraction.failed` and `execution.failed`, both bound to
        the request's correlation_id."""
        workflow_id, _, target_url_id, target_url = await _setup_published(api_client)
        respx.get(target_url).mock(return_value=httpx.Response(503))

        correlation_id = "contract-fail-001"
        caplog_structlog.clear()
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            headers={"X-Request-ID": correlation_id},
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200, r.text
        assert r.json()["execution"]["status"] == "failed"

        events = {str(e.get("event", "")): e for e in caplog_structlog}
        assert "extraction.failed" in events
        assert "execution.failed" in events
        assert events["extraction.failed"]["correlation_id"] == correlation_id
        assert events["execution.failed"]["correlation_id"] == correlation_id
        assert events["execution.failed"]["error_code"] is not None


# ---------------------------------------------------------------------------
# AC-7 No body logging + AC-8 Access log policy
# ---------------------------------------------------------------------------


class TestRequestLoggingPolicy:
    async def test_ac7_post_body_never_appears_in_log(
        self,
        api_client: AsyncClient,
        caplog_structlog: list[dict[str, Any]],
    ) -> None:
        """AC-7: a POST with a body yields no `body`/`payload` kwarg on the
        `request.completed` event, even on the error path."""
        caplog_structlog.clear()
        secret_marker = "super-sensitive-request-body-9df1"
        r = await api_client.post(
            f"{API}/websites",
            json={"host": "", "display_name": secret_marker},
        )
        # Validation failure: error path, body still must not leak into logs.
        assert r.status_code in {400, 422}

        request_events = [
            e for e in caplog_structlog if str(e.get("event", "")) == "request.completed"
        ]
        assert request_events, "expected at least one request.completed event"
        for event in request_events:
            assert "body" not in event
            assert "payload" not in event
            # Full event dict rendered as JSON must not contain the marker.
            assert secret_marker not in json.dumps(event, default=str)

    async def test_ac8_single_request_completed_no_uvicorn_access(
        self,
        api_client: AsyncClient,
        caplog_structlog: list[dict[str, Any]],
    ) -> None:
        """AC-8: one HTTP call → exactly one `request.completed`, zero
        `uvicorn.access` records at INFO."""
        caplog_structlog.clear()
        r = await api_client.get(f"{API}/websites")
        assert r.status_code == 200, r.text

        request_events = [
            e for e in caplog_structlog if str(e.get("event", "")) == "request.completed"
        ]
        assert len(request_events) == 1

        # uvicorn.access stays at WARNING; nothing at INFO should surface.
        assert logging.getLogger("uvicorn.access").getEffectiveLevel() >= logging.WARNING


# ---------------------------------------------------------------------------
# AC-1 + AC-9 Canonical catalogue conformance
# ---------------------------------------------------------------------------


# Mirror of spec 0011 § Canonical event catalogue. If you add a row to the
# spec table, add it here; if a test fails because an emitted event is not
# in this set, that is the drift AC-9 is meant to catch, extend the spec
# first, then this set.
CANONICAL_EVENTS: frozenset[str] = frozenset(
    {
        "app.startup_completed",
        "app.shutdown_started",
        "request.completed",
        "execution.started",
        "execution.completed",
        "execution.failed",
        "execution.terminal_persist_failed",
        "extraction.fetch_started",
        "extraction.fetch_completed",
        "extraction.parse_completed",
        "extraction.extract_completed",
        "extraction.validate_completed",
        "extraction.item_extracted",
        "extraction.failed",
        "log.emission_failed",
    }
)

# AC-12 forbids the pre apply bare names ever showing up again.
FORBIDDEN_BARE_EVENTS: frozenset[str] = frozenset({"startup", "shutdown", "request"})


_EVENT_NAME_RE = __import__("re").compile(r"^[a-z]+\.[a-z0-9_]+$")


def test_ac1_catalogue_events_match_shape() -> None:
    """Every event in the catalogue mirror conforms to the AC-1 shape
    `<domain>.<action>_<outcome>` (lowercase, snake_case). Allowed
    domains are enumerated in spec 0011 § Standard definition § Event
    name shape; keep the regex above in sync with that list."""
    allowed_domains = {"app", "request", "execution", "extraction", "log"}
    for event in CANONICAL_EVENTS:
        assert _EVENT_NAME_RE.match(event), f"catalogue entry {event!r} violates AC-1 shape"
        domain = event.split(".", 1)[0]
        assert domain in allowed_domains, f"catalogue entry {event!r} uses undeclared domain"


def _non_debug_events(entries: list[dict[str, Any]]) -> set[str]:
    """Return the set of event names emitted at INFO or above.

    AC-9 governs events that reach the renderer under the production
    baseline (`LOG_LEVEL=INFO`). The `caplog_structlog` fixture captures
    every call before the filtering wrapper runs, so DEBUG only
    instrumentation (e.g. the `metrics.*` helpers in
    `app.core.observability.metrics`, which run at DEBUG and are
    filtered out in production) would show up here otherwise.
    """
    return {
        str(e.get("event", ""))
        for e in entries
        if e.get("event") and str(e.get("log_level", e.get("level", ""))).lower() != "debug"
    }


class TestCataloguConformanceEndToEnd:
    """AC-9 drift catcher: every INFO or higher event emitted during a
    happy and a failed execution must be in the canonical catalogue. A
    test failure here means either a new event was added without a spec
    update, or an old event was renamed and the catalogue mirror is
    stale."""

    @respx.mock
    async def test_happy_path_only_emits_catalogue_events(
        self,
        api_client: AsyncClient,
        caplog_structlog: list[dict[str, Any]],
    ) -> None:
        workflow_id, _version_id, target_url_id, target_url = await _setup_published(
            api_client,
        )
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200, text=BASIC_HTML, headers={"content-type": "text/html; charset=utf-8"}
            )
        )
        caplog_structlog.clear()
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            headers={"X-Request-ID": "catalogue-happy"},
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200, r.text

        emitted = _non_debug_events(caplog_structlog)
        strays = emitted - CANONICAL_EVENTS
        assert not strays, (
            f"INFO+ events emitted but not in the canonical catalogue: {sorted(strays)}; "
            "add them to spec 0011's catalogue table (and this mirror) before merging."
        )

    @respx.mock
    async def test_failed_path_only_emits_catalogue_events(
        self,
        api_client: AsyncClient,
        caplog_structlog: list[dict[str, Any]],
    ) -> None:
        workflow_id, _version_id, target_url_id, target_url = await _setup_published(
            api_client,
        )
        respx.get(target_url).mock(return_value=httpx.Response(503))
        caplog_structlog.clear()
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            headers={"X-Request-ID": "catalogue-fail"},
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200, r.text

        emitted = _non_debug_events(caplog_structlog)
        strays = emitted - CANONICAL_EVENTS
        assert (
            not strays
        ), f"INFO+ events emitted but not in the canonical catalogue: {sorted(strays)}"


class TestAc12NoBareEventNames:
    """AC-12 explicit regression: the apply pass renamed `startup`,
    `shutdown`, and `request` to their catalogue forms. These names
    must never resurface."""

    @respx.mock
    async def test_no_bare_names_on_happy_execute(
        self,
        api_client: AsyncClient,
        caplog_structlog: list[dict[str, Any]],
    ) -> None:
        workflow_id, _version_id, target_url_id, target_url = await _setup_published(
            api_client,
        )
        respx.get(target_url).mock(
            return_value=httpx.Response(
                200, text=BASIC_HTML, headers={"content-type": "text/html; charset=utf-8"}
            )
        )
        caplog_structlog.clear()
        r = await api_client.post(
            f"{API}/workflows/{workflow_id}/execute",
            headers={"X-Request-ID": "ac12-bare"},
            json={"target_url_id": target_url_id},
        )
        assert r.status_code == 200, r.text

        emitted = _non_debug_events(caplog_structlog)
        regressions = emitted & FORBIDDEN_BARE_EVENTS
        assert (
            not regressions
        ), f"bare event names re-appeared (AC-12 regression): {sorted(regressions)}"


# ---------------------------------------------------------------------------
# AC-4 Programmatic caller: future worker surface with no inbound correlation_id
# ---------------------------------------------------------------------------


class _StubExtractionPort:
    """Minimal `ExtractionPort` double for the AC-4 programmatic path.

    Lets us drive `ExecutionService.execute` without wiring the real HTTP
    + persistence stack; we only care which contextvars are bound while
    extraction runs and what correlation_id persists on the row.
    """

    def __init__(self) -> None:
        self.observed_contextvars: dict[str, Any] = {}

    async def run(self, _workflow_version: Any, _target_url: str) -> Any:
        import structlog

        self.observed_contextvars = dict(structlog.contextvars.get_contextvars())
        # Return a successful extraction result shape the service accepts.
        from app.domains.extraction.schemas import ExtractionResult

        return ExtractionResult(status="completed", items=[], items_count=0, duration_ms=1)


async def test_ac4_execute_mints_correlation_id_when_caller_omits_it() -> None:
    """AC-4 programmatic caller: when a caller (e.g. a future worker)
    invokes `ExecutionService.execute` with no `correlation_id`, a fresh
    UUID4 is minted and bound for the duration of the call, visible to
    the extraction stage, and persisted on `executions.correlation_id`.
    Fully mocked below `ExecutionService` so this stays a unit test; the
    HTTP boundary case is covered by `TestCorrelationPropagationHappy`.
    """
    import uuid

    from app.core.targets import TargetSummary
    from app.core.workflows import VersionSummary, WorkflowSummary
    from app.domains.executions.service import ExecutionService

    workflow_id = uuid.uuid4()
    version_id = uuid.uuid4()
    website_id = uuid.uuid4()
    target_id = uuid.uuid4()

    workflow_summary = WorkflowSummary(
        id=workflow_id,
        website_id=website_id,
        current_version_id=version_id,
        status="active",
    )
    version_summary = VersionSummary(
        id=version_id,
        workflow_id=workflow_id,
        status="published",
        config={},
    )
    target_summary = TargetSummary(
        id=target_id,
        website_id=website_id,
        url="https://example.com/x",
    )

    class _WorkflowPort:
        async def get_live_workflow(self, _wid: uuid.UUID) -> WorkflowSummary:
            return workflow_summary

        async def get_version_for_workflow(
            self, *, workflow_id: uuid.UUID, version_id: uuid.UUID
        ) -> VersionSummary:
            return version_summary

    class _TargetPort:
        async def get_live_target(self, _tid: uuid.UUID) -> TargetSummary:
            return target_summary

    class _ExecutionRepo:
        async def add(self, _execution: Any) -> None:
            return None

        async def finalise(self, _execution: Any) -> None:
            return None

    class _ResultRepo:
        async def add_many(self, _rows: list[Any]) -> None:
            return None

    class _Session:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    port = _StubExtractionPort()
    service = ExecutionService(
        session=_Session(),  # type: ignore[arg-type]
        execution_repo=_ExecutionRepo(),  # type: ignore[arg-type]
        result_repo=_ResultRepo(),  # type: ignore[arg-type]
        workflow_port=_WorkflowPort(),  # type: ignore[arg-type]
        target_port=_TargetPort(),  # type: ignore[arg-type]
        extraction=port,  # type: ignore[arg-type]
    )

    execution = await service.execute(
        workflow_id=workflow_id,
        target_url_id=target_id,
        version_id=None,
    )

    assert execution.correlation_id, "programmatic caller should receive a minted id"
    uuid.UUID(execution.correlation_id)  # parseable as a UUID4 string
    # The same id was bound into structlog contextvars for the duration of
    # the call, visible to the extraction port.
    assert port.observed_contextvars.get("correlation_id") == execution.correlation_id
    assert port.observed_contextvars.get("execution_id") == str(execution.id)

"""Unit tests для RequestIdMiddleware + logging filter (#106)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.observability import (
    REQUEST_ID_HEADER,
    RequestIdLogFilter,
    RequestIdMiddleware,
    get_request_id,
)
from src.api.observability.context import REQUEST_ID_CONTEXT
from src.api.observability.request_id import _parse_or_generate

# ---------------------------------------------------------------------------
# _parse_or_generate


def test_parse_returns_uuid_unchanged() -> None:
    given = "550e8400-e29b-41d4-a716-446655440000"
    assert _parse_or_generate(given) == given


def test_parse_generates_uuid_for_missing() -> None:
    out = _parse_or_generate(None)
    UUID(out)  # raises if not UUID


def test_parse_generates_uuid_for_invalid() -> None:
    """Anti log-injection: невалидный input → fresh uuid, не raw string."""
    out = _parse_or_generate("not-a-uuid; DROP TABLE--")
    UUID(out)


def test_parse_generates_uuid_for_empty_string() -> None:
    out = _parse_or_generate("")
    UUID(out)


def test_parse_generates_uuid_for_non_ascii_garbage() -> None:
    """Newlines / control chars в incoming header → reject через UUID validation."""
    for raw in ("\n\r\tinjected", "x\x00y", "??????"):
        out = _parse_or_generate(raw)
        UUID(out)
        assert out != raw


# ---------------------------------------------------------------------------
# Middleware via TestClient


@pytest.fixture
def client_with_middleware() -> TestClient:
    """TestClient hits real app — middleware is wired in main.py."""
    return TestClient(app)


def test_middleware_echoes_supplied_request_id(
    client_with_middleware: TestClient,
) -> None:
    given = "550e8400-e29b-41d4-a716-446655440000"
    resp = client_with_middleware.get(
        "/api/v1/health",
        headers={REQUEST_ID_HEADER: given},
    )
    assert resp.headers[REQUEST_ID_HEADER] == given


def test_middleware_generates_request_id_when_missing(
    client_with_middleware: TestClient,
) -> None:
    resp = client_with_middleware.get("/api/v1/health")
    out = resp.headers[REQUEST_ID_HEADER]
    UUID(out)  # raises if not UUID


def test_middleware_rejects_malformed_id_generates_new(
    client_with_middleware: TestClient,
) -> None:
    resp = client_with_middleware.get(
        "/api/v1/health",
        headers={REQUEST_ID_HEADER: "not-a-uuid"},
    )
    out = resp.headers[REQUEST_ID_HEADER]
    UUID(out)
    assert out != "not-a-uuid"


def test_middleware_resets_contextvar_after_request(
    client_with_middleware: TestClient,
) -> None:
    """После request'а contextvar должен вернуться к default `'-'`."""
    client_with_middleware.get("/api/v1/health")
    assert get_request_id() == "-"


# ---------------------------------------------------------------------------
# Logging filter


def test_filter_injects_request_id_into_record() -> None:
    f = RequestIdLogFilter()
    token = REQUEST_ID_CONTEXT.set("test-id-123")
    try:
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is True
        assert getattr(record, "request_id") == "test-id-123"  # noqa: B009
    finally:
        REQUEST_ID_CONTEXT.reset(token)


def test_filter_uses_sentinel_when_outside_request() -> None:
    f = RequestIdLogFilter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert getattr(record, "request_id") == "-"  # noqa: B009


# ---------------------------------------------------------------------------
# SSE non-regression — middleware shouldn't break StreamingResponse.


def _build_sse_app() -> FastAPI:
    """Minimal FastAPI app с RequestIdMiddleware + SSE route — закрывает
    утверждение о pure-ASGI совместимости с streaming (см. request_id.py:3-4)."""
    sse_app = FastAPI()
    sse_app.add_middleware(RequestIdMiddleware)

    async def _gen() -> AsyncIterator[bytes]:
        for i in range(3):
            yield f"data: chunk-{i}\n\n".encode()

    @sse_app.get("/stream")
    async def stream_endpoint() -> StreamingResponse:
        return StreamingResponse(_gen(), media_type="text/event-stream")

    return sse_app


def test_middleware_preserves_streaming_response() -> None:
    with TestClient(_build_sse_app()) as c:
        resp = c.get("/stream")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        # Response carries X-Request-Id (set on http.response.start, the
        # streaming chunks don't break it).
        UUID(resp.headers[REQUEST_ID_HEADER])
        # All 3 chunks delivered.
        body = resp.text
        assert "chunk-0" in body
        assert "chunk-1" in body
        assert "chunk-2" in body


# ---------------------------------------------------------------------------
# Concurrent contextvar isolation.


@pytest.mark.asyncio
async def test_contextvar_isolated_across_concurrent_tasks() -> None:
    """ContextVar по spec'у per-Task — две concurrent корутины с разными
    request_id не должны видеть значения друг друга."""

    async def _task(rid: str) -> str:
        token = REQUEST_ID_CONTEXT.set(rid)
        try:
            # Yield to let interleaving happen.
            await asyncio.sleep(0.01)
            return REQUEST_ID_CONTEXT.get()
        finally:
            REQUEST_ID_CONTEXT.reset(token)

    a, b, c = await asyncio.gather(_task("A"), _task("B"), _task("C"))
    assert (a, b, c) == ("A", "B", "C")


# ---------------------------------------------------------------------------
# Response header dedup — downstream-set X-Request-Id не должен дублироваться.


def test_middleware_dedupes_downstream_set_header() -> None:
    """Если inner handler/middleware ставит X-Request-Id (proxy-forwarding
    pattern), outer RequestIdMiddleware должен strip и установить свой
    authoritative value."""
    app2 = FastAPI()

    @app2.get("/echo")
    async def echo() -> dict[str, str]:
        return {"ok": "1"}

    # Order matters: `@app.middleware("http")` (BaseHTTPMiddleware-flavored)
    # регистрируется ПЕРВЫМ → INNER.
    @app2.middleware("http")
    async def add_stale_downstream(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = "stale-downstream-value"
        return response

    # RequestIdMiddleware регистрируется ПОСЛЕДНИМ → OUTERMOST → видит
    # http.response.start от inner middleware'а с уже выставленным
    # X-Request-Id и должен strip + replace.
    app2.add_middleware(RequestIdMiddleware)

    given = "550e8400-e29b-41d4-a716-446655440000"
    with TestClient(app2) as c:
        resp = c.get("/echo", headers={REQUEST_ID_HEADER: given})
        # Authoritative value (от outermost RequestIdMiddleware) wins,
        # без duplicate / comma-concatenation от inner middleware'а.
        assert resp.headers[REQUEST_ID_HEADER] == given
        assert "stale-downstream-value" not in resp.headers[REQUEST_ID_HEADER]

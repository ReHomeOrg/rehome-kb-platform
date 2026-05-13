"""Unit tests для Prometheus metrics middleware + /metrics endpoint (#108)."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST

from src.api.main import app
from src.api.observability.metrics import (
    MetricsMiddleware,
    render_metrics,
)

# Sample extraction через stable `generate_latest()` text format — НЕ через
# `_value.get()` internals (private API; CLAUDE.md §"Костыли" запрещает
# импорт `_private` без явного обоснования).


def _read_sample(needle_prefix: str) -> float:
    """Find line starting with `needle_prefix` (full sample name + labels)
    в Prometheus text snapshot, parse trailing value."""
    snapshot = render_metrics()[0].decode("utf-8")
    for line in snapshot.splitlines():
        if line.startswith(needle_prefix):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def _counter_value(method: str, route: str, status: str) -> float:
    needle = f'http_requests_total{{method="{method}",route="{route}",status="{status}"}}'
    return _read_sample(needle)


def _histogram_sample_count(method: str, route: str) -> int:
    needle = f'http_request_duration_seconds_count{{method="{method}",route="{route}"}}'
    return int(_read_sample(needle))


# ---------------------------------------------------------------------------
# render_metrics


def test_render_metrics_returns_prometheus_text() -> None:
    body, content_type = render_metrics()
    assert content_type == CONTENT_TYPE_LATEST
    # Format должен быть parseable Prometheus text:
    # # HELP <name> <description>
    # # TYPE <name> <type>
    # <name>{...} <value>
    assert b"# HELP http_requests_total" in body
    assert b"# TYPE http_requests_total counter" in body
    assert b"# TYPE http_request_duration_seconds histogram" in body


# ---------------------------------------------------------------------------
# /metrics endpoint


@pytest.fixture
def client_with_app() -> TestClient:
    return TestClient(app)


def test_metrics_endpoint_returns_200_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`METRICS_ENABLED=true` → serve Prometheus snapshot."""
    monkeypatch.setenv("METRICS_ENABLED", "true")
    with TestClient(app) as c:
        resp = c.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert "http_requests_total" in resp.text


def test_metrics_endpoint_returns_404_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safe-by-default: без явного `METRICS_ENABLED=true` → 404."""
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    with TestClient(app) as c:
        resp = c.get("/metrics")
        assert resp.status_code == 404


def test_metrics_endpoint_excluded_from_openapi(
    client_with_app: TestClient,
) -> None:
    """`/metrics` — infra endpoint, не должен светиться в OpenAPI."""
    schema = client_with_app.get("/openapi.json").json()
    assert "/metrics" not in schema.get("paths", {})


# ---------------------------------------------------------------------------
# MetricsMiddleware behavior


def _build_metrics_app() -> FastAPI:
    """Mini-app для изоляции counter/histogram increments от других тестов."""
    test_app = FastAPI()
    test_app.add_middleware(MetricsMiddleware)

    @test_app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"ok": "1"}

    @test_app.get("/error")
    async def err() -> dict[str, str]:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="boom")

    async def _gen() -> AsyncIterator[bytes]:
        for i in range(2):
            yield f"chunk-{i}\n".encode()

    @test_app.get("/stream")
    async def stream() -> StreamingResponse:
        return StreamingResponse(_gen(), media_type="text/plain")

    return test_app


def test_middleware_increments_counter_on_2xx() -> None:
    test_app = _build_metrics_app()
    before = _counter_value("GET", "/hello", "200")
    with TestClient(test_app) as c:
        resp = c.get("/hello")
        assert resp.status_code == 200
    after = _counter_value("GET", "/hello", "200")
    assert after == before + 1


def test_middleware_increments_counter_on_5xx() -> None:
    test_app = _build_metrics_app()
    before = _counter_value("GET", "/error", "500")
    with TestClient(test_app) as c:
        resp = c.get("/error")
        assert resp.status_code == 500
    after = _counter_value("GET", "/error", "500")
    assert after == before + 1


def test_middleware_observes_histogram() -> None:
    test_app = _build_metrics_app()
    before = _histogram_sample_count("GET", "/hello")
    with TestClient(test_app) as c:
        c.get("/hello")
        c.get("/hello")
    after = _histogram_sample_count("GET", "/hello")
    assert after >= before + 2


def test_middleware_does_not_break_streaming() -> None:
    """SSE non-regression — middleware не буфферизует и не ломает chunks."""
    test_app = _build_metrics_app()
    with TestClient(test_app) as c:
        resp = c.get("/stream")
        assert resp.status_code == 200
        assert "chunk-0" in resp.text
        assert "chunk-1" in resp.text


def test_middleware_uses_route_pattern_not_raw_path() -> None:
    """Cardinality discipline — UUID не должен попадать в `route` label."""
    test_app = FastAPI()
    test_app.add_middleware(MetricsMiddleware)

    @test_app.get("/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    with TestClient(test_app) as c:
        c.get("/items/abc-123-uuid-aaaa")
        c.get("/items/different-id-bbbb")

    # Both requests should land in the SAME label-bucket `/items/{item_id}`,
    # не в two separate buckets.
    count = _counter_value("GET", "/items/{item_id}", "200")
    assert count >= 2


def test_middleware_falls_back_to_unmatched_for_404() -> None:
    test_app = FastAPI()
    test_app.add_middleware(MetricsMiddleware)

    with TestClient(test_app) as c:
        c.get("/no-such-path-9999")

    # 404 paths landed в `<unmatched>` bucket — не утекают raw paths
    # в Prometheus labels.
    assert _counter_value("GET", "<unmatched>", "404") >= 1

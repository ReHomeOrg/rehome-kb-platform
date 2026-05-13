"""Unit tests для RequestIdMiddleware + logging filter (#106)."""

import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.observability import (
    REQUEST_ID_HEADER,
    RequestIdLogFilter,
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
        assert record.request_id == "test-id-123"  # type: ignore[attr-defined]
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
    assert record.request_id == "-"  # type: ignore[attr-defined]

"""Tests for /api/v1/health and /api/v1/version."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.db import get_session
from src.api.main import app


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_returns_all_required_fields(client: TestClient) -> None:
    response = client.get("/api/v1/version")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"api_version", "build_hash", "build_date", "environment"}
    for value in body.values():
        assert isinstance(value, str)
        assert value


def test_version_uses_env_vars(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard against hardcoded values: env override must propagate to response."""
    monkeypatch.setenv("REHOME_API_VERSION", "9.9.9-test")
    monkeypatch.setenv("GIT_COMMIT", "abc1234")
    monkeypatch.setenv("BUILD_DATE", "2026-05-11T12:00:00Z")
    monkeypatch.setenv("REHOME_ENV", "staging")

    response = client.get("/api/v1/version")
    body = response.json()
    assert body["api_version"] == "9.9.9-test"
    assert body["build_hash"] == "abc1234"
    assert body["build_date"] == "2026-05-11T12:00:00Z"
    assert body["environment"] == "staging"


def test_version_default_values_when_no_env(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When env is empty, defaults from Settings must be served."""
    monkeypatch.delenv("REHOME_API_VERSION", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.delenv("BUILD_DATE", raising=False)
    monkeypatch.delenv("REHOME_ENV", raising=False)

    response = client.get("/api/v1/version")
    body = response.json()
    assert body["api_version"] == "1.0.0-alpha"
    assert body["build_hash"] == "unknown"
    assert body["build_date"] == "unknown"
    assert body["environment"] == "dev"


# ---------------------------------------------------------------------------
# /ready (#112)


def test_ready_returns_200_when_db_ping_succeeds(client: TestClient) -> None:
    """DB available → 200, body matches OpenAPI ReadinessResponse."""

    async def _ok_session() -> AsyncIterator[Any]:
        session = MagicMock()
        session.execute = AsyncMock(return_value=None)
        yield session

    app.dependency_overrides[get_session] = _ok_session
    try:
        resp = client.get("/api/v1/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["dependencies"]["db"] == "ok"
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_ready_returns_503_when_db_raises(client: TestClient) -> None:
    """DB error → 503; ФЗ-152: exception text НЕ в response body."""

    async def _broken_session() -> AsyncIterator[Any]:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=RuntimeError("db gone"))
        yield session

    app.dependency_overrides[get_session] = _broken_session
    try:
        resp = client.get("/api/v1/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"
        assert body["dependencies"]["db"] == "down"
        # ФЗ-152 — exception detail НЕ в response body.
        assert "db gone" not in resp.text
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_ready_returns_503_on_db_timeout(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB slow > timeout → 503."""
    monkeypatch.setenv("READINESS_DB_TIMEOUT_SECONDS", "0.05")

    async def _slow_query(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0.5)

    async def _slow_session() -> AsyncIterator[Any]:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=_slow_query)
        yield session

    app.dependency_overrides[get_session] = _slow_session
    try:
        resp = client.get("/api/v1/ready")
        assert resp.status_code == 503
        assert resp.json()["dependencies"]["db"] == "down"
    finally:
        app.dependency_overrides.pop(get_session, None)

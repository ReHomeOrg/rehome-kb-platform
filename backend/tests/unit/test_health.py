"""Tests for /api/v1/health and /api/v1/version."""

import pytest
from fastapi.testclient import TestClient


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

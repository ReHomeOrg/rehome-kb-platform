"""Unit tests для PATCH /admin/system-config + PUT /admin/llm/active (#264)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.system_config_repository import (
    UnknownKeyError,
    get_system_config_repository,
)
from src.api.audit.repository import get_audit_repository
from src.api.main import app


@pytest.fixture
def config_repo_mock() -> Iterator[dict[str, AsyncMock]]:
    read = AsyncMock(return_value={"llm_provider": "mock"})
    patch = AsyncMock(return_value={"llm_provider": "mock"})

    class _FakeRepo:
        def __init__(self) -> None:
            self.read = read
            self.patch = patch

    app.dependency_overrides[get_system_config_repository] = lambda: _FakeRepo()
    yield {"read": read, "patch": patch}
    app.dependency_overrides.pop(get_system_config_repository, None)


@pytest.fixture
def audit_repo_mock() -> Iterator[AsyncMock]:
    record = AsyncMock()

    class _FakeRepo:
        def __init__(self) -> None:
            self.record = record

    app.dependency_overrides[get_audit_repository] = lambda: _FakeRepo()
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


# ---------------------------------------------------------------------------
# PATCH /admin/system-config


def test_patch_anon_returns_401(client: TestClient) -> None:
    resp = client.patch("/api/v1/admin/system-config", json={})
    assert resp.status_code == 401


def test_patch_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_patch_staff_admin_updates_allowed_key(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    config_repo_mock["patch"].return_value = {"llm_provider": "gigachat"}
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={"llm_provider": "gigachat"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-MFA-Token": "test-mfa-token",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["llm_config"]["active_provider"] == "gigachat"
    config_repo_mock["patch"].assert_awaited_once()
    # audit запись содержит keys + mfa_token_provided=True.
    audit_repo_mock.assert_awaited_once()
    md = audit_repo_mock.call_args.kwargs["metadata"]
    assert md["keys"] == ["llm_provider"]
    assert md["mfa_token_provided"] is True


def test_patch_unknown_key_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    config_repo_mock["patch"].side_effect = UnknownKeyError(["secret"])
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={"secret": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    audit_repo_mock.assert_not_awaited()


def test_patch_without_mfa_token_still_works_but_audited(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """Honest stub: X-MFA-Token not validated, but presence logged."""
    config_repo_mock["patch"].return_value = {}
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    md = audit_repo_mock.call_args.kwargs["metadata"]
    assert md["mfa_token_provided"] is False


# ---------------------------------------------------------------------------
# PUT /admin/llm/active


def test_put_active_anon_returns_401(client: TestClient) -> None:
    resp = client.put("/api/v1/admin/llm/active", json={"provider_id": "mock"})
    assert resp.status_code == 401


def test_put_active_tenant_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.put(
        "/api/v1/admin/llm/active",
        json={"provider_id": "mock"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_put_active_staff_admin_sets_provider(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    config_repo_mock["patch"].return_value = {"llm_provider": "yandex_gpt"}
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.put(
        "/api/v1/admin/llm/active",
        json={"provider_id": "yandex_gpt", "reason": "A/B test"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-MFA-Token": "tok",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_provider"] == "yandex_gpt"
    # Audit metadata includes provider_id + reason.
    md = audit_repo_mock.call_args.kwargs["metadata"]
    assert md["provider_id"] == "yandex_gpt"
    assert md["reason"] == "A/B test"


def test_put_active_missing_provider_id_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.put(
        "/api/v1/admin/llm/active",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_get_system_config_includes_overlay(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
) -> None:
    """GET projection теперь использует overlay из repo (ADR-0019)."""
    config_repo_mock["read"].return_value = {
        "llm_provider": "gigachat",
        "llm_fallback_provider": "mock",
    }
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/system-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["llm_config"]["active_provider"] == "gigachat"
    assert body["llm_config"]["fallback_provider"] == "mock"

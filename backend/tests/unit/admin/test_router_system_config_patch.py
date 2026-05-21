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
    sub = str(uuid4())
    token = make_jwt(roles=["staff_admin"], sub=sub)
    mfa_token = make_jwt(roles=["staff_admin"], sub=sub, extra_claims={"acr": "2"})
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={"llm_provider": "gigachat"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-MFA-Token": mfa_token,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["llm_config"]["active_provider"] == "gigachat"
    config_repo_mock["patch"].assert_awaited_once()
    # Audit запись содержит mfa_acr из validated token (string "2").
    audit_repo_mock.assert_awaited_once()
    md = audit_repo_mock.call_args.kwargs["metadata"]
    assert md["keys"] == ["llm_provider"]
    assert md["mfa_acr"] == "2"


def test_patch_unknown_key_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    config_repo_mock["patch"].side_effect = UnknownKeyError(["secret"])
    sub = str(uuid4())
    token = make_jwt(roles=["staff_admin"], sub=sub)
    mfa_token = make_jwt(roles=["staff_admin"], sub=sub, extra_claims={"acr": "2"})
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={"secret": "x"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-MFA-Token": mfa_token,
        },
    )
    assert resp.status_code == 422
    audit_repo_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# X-MFA-Token validation (ADR-0019 §«MFA» landed)


def test_patch_without_mfa_token_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """Missing X-MFA-Token → 403 (was honest-stub 200 в #264)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "X-MFA-Token" in resp.json()["detail"]
    audit_repo_mock.assert_not_awaited()


def test_patch_mfa_token_with_low_acr_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """acr=1 (single-factor) → 403 (требуется acr=2)."""
    sub = str(uuid4())
    token = make_jwt(roles=["staff_admin"], sub=sub)
    weak_mfa = make_jwt(roles=["staff_admin"], sub=sub, extra_claims={"acr": "1"})
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={},
        headers={"Authorization": f"Bearer {token}", "X-MFA-Token": weak_mfa},
    )
    assert resp.status_code == 403
    assert "acr" in resp.json()["detail"]


def test_patch_mfa_token_with_wrong_sub_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """Anti-token-swap: MFA token issued for another user → 403."""
    main_sub = str(uuid4())
    other_sub = str(uuid4())
    token = make_jwt(roles=["staff_admin"], sub=main_sub)
    swapped_mfa = make_jwt(roles=["staff_admin"], sub=other_sub, extra_claims={"acr": "2"})
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={},
        headers={"Authorization": f"Bearer {token}", "X-MFA-Token": swapped_mfa},
    )
    assert resp.status_code == 403
    assert "sub mismatch" in resp.json()["detail"].lower()


def test_patch_mfa_token_invalid_signature_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """Malformed / unsigned MFA token → 403."""
    sub = str(uuid4())
    token = make_jwt(roles=["staff_admin"], sub=sub)
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={},
        headers={"Authorization": f"Bearer {token}", "X-MFA-Token": "not-a-jwt"},
    )
    assert resp.status_code == 403


def test_patch_mfa_token_missing_acr_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """MFA token без acr claim → 403."""
    sub = str(uuid4())
    token = make_jwt(roles=["staff_admin"], sub=sub)
    mfa_no_acr = make_jwt(roles=["staff_admin"], sub=sub)  # no extra_claims
    resp = client.patch(
        "/api/v1/admin/system-config",
        json={},
        headers={"Authorization": f"Bearer {token}", "X-MFA-Token": mfa_no_acr},
    )
    assert resp.status_code == 403


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
    sub = str(uuid4())
    token = make_jwt(roles=["staff_admin"], sub=sub)
    mfa_token = make_jwt(roles=["staff_admin"], sub=sub, extra_claims={"acr": "2"})
    resp = client.put(
        "/api/v1/admin/llm/active",
        json={"provider_id": "yandex_gpt", "reason": "A/B test"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-MFA-Token": mfa_token,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_provider"] == "yandex_gpt"
    # Audit metadata includes provider_id + reason + mfa_acr.
    md = audit_repo_mock.call_args.kwargs["metadata"]
    assert md["provider_id"] == "yandex_gpt"
    assert md["reason"] == "A/B test"
    assert md["mfa_acr"] == "2"


def test_put_active_without_mfa_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.put(
        "/api/v1/admin/llm/active",
        json={"provider_id": "mock"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_put_active_missing_provider_id_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    config_repo_mock: dict[str, AsyncMock],
) -> None:
    sub = str(uuid4())
    token = make_jwt(roles=["staff_admin"], sub=sub)
    mfa_token = make_jwt(roles=["staff_admin"], sub=sub, extra_claims={"acr": "2"})
    resp = client.put(
        "/api/v1/admin/llm/active",
        json={},
        headers={
            "Authorization": f"Bearer {token}",
            "X-MFA-Token": mfa_token,
        },
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

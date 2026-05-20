"""Unit tests для emergency_router (ADR-0021 A)."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.repository import get_audit_repository
from src.api.main import app
from src.api.vault.emergency_repository import get_emergency_repository
from src.api.vault.models import VaultEmergencyUnlockLog, VaultUser
from src.api.vault.repository import VaultRepository, get_vault_repository


def _make_vault_user(*, has_escrow: bool = True) -> VaultUser:
    u = VaultUser()
    u.user_id = uuid4()
    u.argon_salt = b"\x00" * 16
    u.auth_hash = b"\x01" * 32
    u.encrypted_x25519_privkey = b"\x02" * 96
    u.x25519_pubkey = b"\x03" * 32
    u.totp_secret_encrypted = None
    u.escrow_wrap = b"\x04" * 60 if has_escrow else None
    u.created_at = datetime(2026, 5, 20, tzinfo=UTC)
    u.updated_at = u.created_at
    u.last_unlock_at = None
    return u


def _make_log_row(security_incident_id: Any = None) -> VaultEmergencyUnlockLog:
    row = VaultEmergencyUnlockLog()
    row.id = uuid4()
    row.security_incident_id = security_incident_id or uuid4()
    row.rkn_notify_required = False
    row.created_at = datetime(2026, 5, 21, tzinfo=UTC)
    return row


@pytest.fixture
def vault_repo_mock() -> Iterator[MagicMock]:
    repo = MagicMock(spec=VaultRepository)
    repo.get_user = AsyncMock(return_value=None)
    repo.set_escrow_wrap = AsyncMock()
    app.dependency_overrides[get_vault_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_vault_repository, None)


@pytest.fixture
def emergency_repo_mock() -> Iterator[MagicMock]:
    repo = MagicMock()
    repo.log = AsyncMock(return_value=_make_log_row())
    app.dependency_overrides[get_emergency_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_emergency_repository, None)


@pytest.fixture
def audit_spy() -> Iterator[AsyncMock]:
    record = AsyncMock()

    class _FakeRepo:
        def __init__(self) -> None:
            self.record = record

    app.dependency_overrides[get_audit_repository] = lambda: _FakeRepo()
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


# ---------------------------------------------------------------------------
# /vault/setup-escrow


def test_setup_escrow_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/vault/setup-escrow", json={"escrow_wrap_b64": "AA=="})
    assert resp.status_code == 401


def test_setup_escrow_404_when_vault_missing(
    client: TestClient,
    vault_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    vault_repo_mock.set_escrow_wrap = AsyncMock(return_value=None)
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/setup-escrow",
        json={"escrow_wrap_b64": base64.b64encode(b"\x00" * 60).decode("ascii")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_setup_escrow_happy_path_audits(
    client: TestClient,
    vault_repo_mock: MagicMock,
    audit_spy: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    user_id = uuid4()
    vault_repo_mock.set_escrow_wrap = AsyncMock(return_value=_make_vault_user())
    token = make_jwt(roles=["tenant"], sub=str(user_id))
    resp = client.post(
        "/api/v1/vault/setup-escrow",
        json={"escrow_wrap_b64": base64.b64encode(b"\x00" * 60).decode("ascii")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"has_escrow": True}
    audit_spy.assert_awaited_once()
    assert audit_spy.call_args.kwargs["action"] == "vault.escrow.setup"


def test_setup_escrow_rejects_invalid_base64(
    client: TestClient,
    vault_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/setup-escrow",
        json={"escrow_wrap_b64": "@@@not-base64@@@"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_setup_escrow_rejects_too_large_blob(
    client: TestClient,
    vault_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    # 600-byte blob > 512 max.
    resp = client.post(
        "/api/v1/vault/setup-escrow",
        json={"escrow_wrap_b64": base64.b64encode(b"\x00" * 600).decode("ascii")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /admin/vault/emergency-unlock — RBAC


def test_emergency_unlock_anon_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/admin/vault/emergency-unlock",
        json={
            "target_user_id": str(uuid4()),
            "reason_category": "incident",
            "reason_text": "x" * 20,
        },
    )
    assert resp.status_code == 401


def test_emergency_unlock_tenant_returns_403(
    client: TestClient,
    vault_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/vault/emergency-unlock",
        json={
            "target_user_id": str(uuid4()),
            "reason_category": "incident",
            "reason_text": "x" * 20,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_emergency_unlock_staff_support_returns_403(
    client: TestClient,
    vault_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_support имеет STAFF, не LEGAL → 403 (нужно staff_admin)."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/vault/emergency-unlock",
        json={
            "target_user_id": str(uuid4()),
            "reason_category": "incident",
            "reason_text": "x" * 20,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_emergency_unlock_404_when_target_vault_missing(
    client: TestClient,
    vault_repo_mock: MagicMock,
    emergency_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    vault_repo_mock.get_user = AsyncMock(return_value=None)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/vault/emergency-unlock",
        json={
            "target_user_id": str(uuid4()),
            "reason_category": "incident",
            "reason_text": "x" * 20,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_emergency_unlock_404_when_no_escrow_setup(
    client: TestClient,
    vault_repo_mock: MagicMock,
    emergency_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """User has vault но escrow_wrap=None → recovery невозможна."""
    vault_repo_mock.get_user = AsyncMock(return_value=_make_vault_user(has_escrow=False))
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/vault/emergency-unlock",
        json={
            "target_user_id": str(uuid4()),
            "reason_category": "incident",
            "reason_text": "x" * 20,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    assert "escrow" in resp.json()["detail"].lower()


def test_emergency_unlock_happy_path_returns_payload(
    client: TestClient,
    vault_repo_mock: MagicMock,
    emergency_repo_mock: MagicMock,
    audit_spy: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    target = _make_vault_user()
    vault_repo_mock.get_user = AsyncMock(return_value=target)
    fake_incident = MagicMock()
    fake_incident.id = uuid4()
    log_row = _make_log_row(security_incident_id=fake_incident.id)
    emergency_repo_mock.log = AsyncMock(return_value=log_row)

    # Patch service to bypass session.add(SecurityIncident) since
    # TestClient's session is mocked elsewhere.
    with patch(
        "src.api.vault.emergency_router.record_emergency_unlock",
        new=AsyncMock(return_value=log_row),
    ):
        token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
        resp = client.post(
            "/api/v1/admin/vault/emergency-unlock",
            json={
                "target_user_id": str(target.user_id),
                "reason_category": "incident",
                "reason_text": "Suspected breach reported via security@",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["severity"] == "high"
    assert body["security_incident_id"] == str(fake_incident.id)
    assert body["unlock_log_id"] == str(log_row.id)
    assert body["vault"]["escrow_wrap_b64"]
    assert body["vault"]["encrypted_x25519_privkey_b64"]
    assert body["vault"]["argon_salt_b64"]


def test_emergency_unlock_short_reason_text_returns_422(
    client: TestClient,
    vault_repo_mock: MagicMock,
    emergency_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """reason_text min_length=10 — anti-laziness guard."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/vault/emergency-unlock",
        json={
            "target_user_id": str(uuid4()),
            "reason_category": "incident",
            "reason_text": "short",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_emergency_unlock_invalid_reason_category_returns_422(
    client: TestClient,
    vault_repo_mock: MagicMock,
    emergency_repo_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/vault/emergency-unlock",
        json={
            "target_user_id": str(uuid4()),
            "reason_category": "bogus",
            "reason_text": "x" * 20,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

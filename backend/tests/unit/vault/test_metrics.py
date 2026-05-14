"""Unit tests для vault Prometheus metrics (#180)."""

from base64 import b64encode
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit import AuditRepository, get_audit_repository
from src.api.main import app
from src.api.vault.metrics import SECRET_ACCESS_TOTAL, UNLOCK_TOTAL
from src.api.vault.models import VaultUser
from src.api.vault.repository import VaultRepository, get_vault_repository


@pytest.fixture
def repo_mocks() -> dict[str, AsyncMock]:
    return {
        "get_user": AsyncMock(return_value=None),
    }


@pytest.fixture
def audit_record_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def override_deps(
    repo_mocks: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    repo = VaultRepository.__new__(VaultRepository)
    for name, mock in repo_mocks.items():
        setattr(repo, name, mock)
    audit = AuditRepository.__new__(AuditRepository)
    audit.record = audit_record_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_vault_repository] = lambda: repo
    app.dependency_overrides[get_audit_repository] = lambda: audit
    yield repo_mocks
    app.dependency_overrides.pop(get_vault_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)


def _b64(b: bytes) -> str:
    return b64encode(b).decode("ascii")


def _make_user(user_id: UUID) -> VaultUser:
    u = VaultUser()
    u.user_id = user_id
    u.argon_salt = b"\x01" * 16
    u.auth_hash = b"\x02" * 32
    u.encrypted_x25519_privkey = b"\x03" * 64
    u.x25519_pubkey = b"\x04" * 32
    u.totp_secret_encrypted = None
    u.created_at = datetime.now(UTC)
    u.updated_at = datetime.now(UTC)
    u.last_unlock_at = None
    return u


def _counter_value(counter: Any, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())


def test_unlock_success_increments_success_counter(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    user = _make_user(uid)
    auth_hash = b"\x02" * 32
    user.auth_hash = auth_hash
    override_deps["get_user"].return_value = user

    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    before = _counter_value(UNLOCK_TOTAL, result="success")
    resp = client.post(
        "/api/v1/vault/unlock",
        json={"auth_hash_b64": _b64(auth_hash)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    after = _counter_value(UNLOCK_TOTAL, result="success")
    assert after - before == 1.0


def test_unlock_failed_increments_failed_counter(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    user = _make_user(uid)
    user.auth_hash = b"\x02" * 32
    override_deps["get_user"].return_value = user

    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    before = _counter_value(UNLOCK_TOTAL, result="failed")
    resp = client.post(
        "/api/v1/vault/unlock",
        json={"auth_hash_b64": _b64(b"\xff" * 32)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
    after = _counter_value(UNLOCK_TOTAL, result="failed")
    assert after - before == 1.0


def test_unlock_not_setup_increments_failed_counter(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """get_user returns None → 401 + failed counter."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    before = _counter_value(UNLOCK_TOTAL, result="failed")
    resp = client.post(
        "/api/v1/vault/unlock",
        json={"auth_hash_b64": _b64(b"\x02" * 32)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
    after = _counter_value(UNLOCK_TOTAL, result="failed")
    assert after - before == 1.0


def test_secret_access_total_metric_exists() -> None:
    """Smoke test: metric registered с правильными labels."""
    # Should not raise.
    SECRET_ACCESS_TOTAL.labels(action="created", category="infra")
    SECRET_ACCESS_TOTAL.labels(action="read", category="api_key")
    SECRET_ACCESS_TOTAL.labels(action="deleted", category="cert")

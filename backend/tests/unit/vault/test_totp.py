"""Unit tests для vault TOTP setup/disable endpoints (#164)."""

from base64 import b64encode
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit import AuditRepository, get_audit_repository
from src.api.main import app
from src.api.vault.models import VaultUser
from src.api.vault.repository import VaultRepository, get_vault_repository


def _b64(b: bytes) -> str:
    return b64encode(b).decode("ascii")


def _make_user(uid: UUID, totp: bytes | None = None) -> VaultUser:
    u = VaultUser()
    u.user_id = uid
    u.argon_salt = b"\x01" * 16
    u.auth_hash = b"\x02" * 32
    u.encrypted_x25519_privkey = b"\x03" * 64
    u.x25519_pubkey = b"\x04" * 32
    u.totp_secret_encrypted = totp
    u.created_at = datetime.now(UTC)
    u.updated_at = datetime.now(UTC)
    u.last_unlock_at = None
    return u


@pytest.fixture
def repo_mocks() -> dict[str, AsyncMock]:
    return {
        "get_user": AsyncMock(return_value=None),
        "set_totp_secret": AsyncMock(return_value=None),
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
    for name, m in repo_mocks.items():
        setattr(repo, name, m)
    audit = AuditRepository.__new__(AuditRepository)
    audit.record = audit_record_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_vault_repository] = lambda: repo
    app.dependency_overrides[get_audit_repository] = lambda: audit
    yield repo_mocks
    app.dependency_overrides.pop(get_vault_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)


def _setup_payload() -> dict[str, str]:
    return {"totp_secret_encrypted_b64": _b64(b"\xaa" * 60)}


# ---------------------------------------------------------------------------
# POST /vault/totp/setup


def test_totp_setup_requires_auth(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
) -> None:
    resp = client.post("/api/v1/vault/totp/setup", json=_setup_payload())
    assert resp.status_code == 401


def test_totp_setup_404_when_vault_not_setup(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """set_totp_secret returns None если user не существует."""
    override_deps["set_totp_secret"].return_value = None
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/totp/setup",
        json=_setup_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_totp_setup_stores_encrypted_secret_and_audits(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    secret_bytes = b"\xaa" * 60
    override_deps["set_totp_secret"].return_value = _make_user(uid, secret_bytes)
    token = make_jwt(roles=["tenant"], sub=str(uid))
    resp = client.post(
        "/api/v1/vault/totp/setup",
        json={"totp_secret_encrypted_b64": _b64(secret_bytes)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_totp"] is True
    # Audit запись fired.
    assert audit_record_mock.call_args.kwargs["action"] == "vault.totp.enabled"
    # Repository called с decoded bytes.
    call_args = override_deps["set_totp_secret"].call_args
    assert call_args.args[1] == secret_bytes


def test_totp_setup_oversize_ciphertext_returns_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """>256 bytes ciphertext → 422 (anti-DoS)."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/totp/setup",
        json={"totp_secret_encrypted_b64": _b64(b"\x00" * 300)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_totp_setup_malformed_b64_returns_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/totp/setup",
        json={"totp_secret_encrypted_b64": "!!!not-base64!!!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_totp_setup_extra_field_returns_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/totp/setup",
        json={**_setup_payload(), "evil_field": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /vault/totp


def test_totp_disable_requires_auth(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
) -> None:
    resp = client.delete("/api/v1/vault/totp")
    assert resp.status_code == 401


def test_totp_disable_404_when_vault_not_setup(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["get_user"].return_value = None
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.delete(
        "/api/v1/vault/totp",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_totp_disable_404_when_totp_not_enabled(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    override_deps["get_user"].return_value = _make_user(uid, totp=None)
    token = make_jwt(roles=["tenant"], sub=str(uid))
    resp = client.delete(
        "/api/v1/vault/totp",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_totp_disable_success(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    override_deps["get_user"].return_value = _make_user(uid, totp=b"\xaa" * 60)
    override_deps["set_totp_secret"].return_value = _make_user(uid, totp=None)
    token = make_jwt(roles=["tenant"], sub=str(uid))
    resp = client.delete(
        "/api/v1/vault/totp",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    # set_totp_secret called с None.
    call_args = override_deps["set_totp_secret"].call_args
    assert call_args.args[1] is None
    assert audit_record_mock.call_args.kwargs["action"] == "vault.totp.disabled"

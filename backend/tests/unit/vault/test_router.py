"""Unit tests for vault router (#147)."""

from base64 import b64encode
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit import AuditRepository, get_audit_repository
from src.api.main import app
from src.api.vault.models import VaultGroup, VaultSecret, VaultSecretBlob, VaultUser
from src.api.vault.repository import VaultRepository, get_vault_repository


def _b64(b: bytes) -> str:
    return b64encode(b).decode("ascii")


def _make_user(user_id: UUID | None = None) -> VaultUser:
    u = VaultUser()
    u.user_id = user_id or uuid4()
    u.argon_salt = b"\x01" * 16
    u.auth_hash = b"\x02" * 32
    u.encrypted_x25519_privkey = b"\x03" * 64
    u.x25519_pubkey = b"\x04" * 32
    u.totp_secret_encrypted = None
    u.created_at = datetime.now(UTC)
    u.updated_at = datetime.now(UTC)
    u.last_unlock_at = None
    return u


def _make_secret(owner_id: UUID, **over: Any) -> VaultSecret:
    s = VaultSecret()
    s.id = uuid4()
    s.title_ciphertext = b"encrypted-title"
    s.category = "infra"
    s.owner_id = owner_id
    s.created_at = datetime.now(UTC)
    s.updated_at = datetime.now(UTC)
    s.expires_at = None
    s.archived_at = None
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _make_blob(secret_id: UUID, version: int = 1) -> VaultSecretBlob:
    b = VaultSecretBlob()
    b.secret_id = secret_id
    b.ciphertext = b"encrypted-payload"
    b.payload_version = version
    b.updated_at = datetime.now(UTC)
    return b


def _make_group(creator: UUID) -> VaultGroup:
    g = VaultGroup()
    g.id = uuid4()
    g.name = "Team"
    g.description = None
    g.created_by = creator
    g.created_at = datetime.now(UTC)
    return g


@pytest.fixture
def repo_mocks() -> dict[str, AsyncMock]:
    return {
        "get_user": AsyncMock(return_value=None),
        "create_user": AsyncMock(),
        "create_group": AsyncMock(),
        "list_groups_for_user": AsyncMock(return_value=[]),
        "is_group_member": AsyncMock(return_value=False),
        "create_secret": AsyncMock(),
        "get_secret": AsyncMock(return_value=None),
        "get_secret_blob": AsyncMock(return_value=None),
        "get_wraps_for_recipient": AsyncMock(return_value=[]),
        "can_user_access_secret": AsyncMock(return_value=False),
        "update_secret_blob": AsyncMock(return_value=None),
        "archive_secret": AsyncMock(return_value=False),
        # ADR-0017 sharing
        "get_user_pubkey": AsyncMock(return_value=None),
        "add_secret_wraps": AsyncMock(return_value=0),
        "remove_secret_wrap": AsyncMock(return_value=False),
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


# ---------------------------------------------------------------------------
# auth


def test_endpoints_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/vault/me").status_code == 401
    unlock_resp = client.post(
        "/api/v1/vault/unlock",
        json={"auth_hash_b64": _b64(b"x")},
    )
    assert unlock_resp.status_code == 401
    assert client.post("/api/v1/vault/secrets", json={}).status_code == 401


# ---------------------------------------------------------------------------
# GET /me


def test_get_me_not_setup(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get("/api/v1/vault/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["is_setup"] is False
    assert resp.json()["argon_salt_b64"] is None


def test_get_me_setup_returns_crypto_state(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    user = _make_user(uid)
    override_deps["get_user"].return_value = user
    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    resp = client.get("/api/v1/vault/me", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["is_setup"] is True
    assert body["argon_salt_b64"] == _b64(user.argon_salt)
    assert body["x25519_pubkey_b64"] == _b64(user.x25519_pubkey)
    # auth_hash НЕ возвращается (anti-replay).
    assert "auth_hash_b64" not in body


# ---------------------------------------------------------------------------
# POST /setup


def _setup_payload() -> dict[str, str]:
    return {
        "argon_salt_b64": _b64(b"\x01" * 16),
        "auth_hash_b64": _b64(b"\x02" * 32),
        "encrypted_x25519_privkey_b64": _b64(b"\x03" * 64),
        "x25519_pubkey_b64": _b64(b"\x04" * 32),
    }


def test_setup_creates_user(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    override_deps["create_user"].return_value = _make_user(uid)
    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    resp = client.post(
        "/api/v1/vault/setup",
        json=_setup_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    override_deps["create_user"].assert_awaited_once()


def test_setup_409_if_exists(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    override_deps["get_user"].return_value = _make_user(uid)
    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    resp = client.post(
        "/api/v1/vault/setup",
        json=_setup_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_setup_validates_salt_size(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """argon_salt 16 bytes — 20 bytes должен дать 422."""
    payload = _setup_payload() | {"argon_salt_b64": _b64(b"\x01" * 20)}
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/setup",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_setup_malformed_base64_returns_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    payload = _setup_payload() | {"argon_salt_b64": "!!!not-base64"}
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/setup",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /unlock


def test_unlock_success(
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
    resp = client.post(
        "/api/v1/vault/unlock",
        json={"auth_hash_b64": _b64(auth_hash)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # Audit recorded as success.
    audit_record_mock.assert_awaited()
    audit_kwargs = audit_record_mock.call_args.kwargs
    assert audit_kwargs["action"] == "vault.unlock.success"


def test_unlock_failed_audit(
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
    resp = client.post(
        "/api/v1/vault/unlock",
        json={"auth_hash_b64": _b64(b"\xff" * 32)},  # wrong hash
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
    audit_kwargs = audit_record_mock.call_args.kwargs
    assert audit_kwargs["action"] == "vault.unlock.failed"


def test_unlock_when_not_setup_returns_401(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """get_user returns None → mismatched, 401."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/vault/unlock",
        json={"auth_hash_b64": _b64(b"\x02" * 32)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Secrets validation


def _secret_create_payload(self_user: UUID, **over: Any) -> dict[str, Any]:
    payload = {
        "title_ciphertext_b64": _b64(b"encrypted-title"),
        "category": "infra",
        "blob_ciphertext_b64": _b64(b"encrypted-payload"),
        "wraps": [
            {
                "user_id": str(self_user),
                "wrapped_key_b64": _b64(b"\xaa" * 48),
            }
        ],
    }
    payload.update(over)
    return payload


def test_create_secret_rejects_when_creator_not_in_wraps(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    other = uuid4()
    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    payload = _secret_create_payload(other)  # wraps target другого user
    resp = client.post(
        "/api/v1/vault/secrets",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_secret_rejects_wrap_without_user_or_group(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    payload = _secret_create_payload(uid, wraps=[{"wrapped_key_b64": _b64(b"\xaa" * 48)}])
    resp = client.post(
        "/api/v1/vault/secrets",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    # Это HTTPException 422 от router'а (not Pydantic validator).
    assert resp.status_code == 422


def test_create_secret_group_lineage_requires_membership(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """ADR-0017: wrap с group_id lineage для группы, где caller — не member,
    должен быть отклонён 403 (можно «помечать» только свои группы)."""
    uid = uuid4()
    other_uid = uuid4()
    gid = uuid4()
    override_deps["is_group_member"].return_value = False  # not member
    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    payload = _secret_create_payload(uid)
    # ADR-0017 wraps require user_id; group_id — optional lineage.
    payload["wraps"].append(
        {
            "user_id": str(other_uid),
            "group_id": str(gid),
            "wrapped_key_b64": _b64(b"\xbb" * 48),
        }
    )
    resp = client.post(
        "/api/v1/vault/secrets",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_create_secret_oversized_blob_returns_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """blob > 64 KiB → 422 (anti-DoS)."""
    uid = uuid4()
    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    payload = _secret_create_payload(uid)
    payload["blob_ciphertext_b64"] = _b64(b"\x00" * (65 * 1024))
    resp = client.post(
        "/api/v1/vault/secrets",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Secrets read


def test_get_secret_not_found(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/vault/secrets/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_delete_secret_only_owner(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Non-owner attempt → 404 (anti-enumeration)."""
    owner = uuid4()
    secret = _make_secret(owner)
    override_deps["get_secret"].return_value = secret

    other = uuid4()
    token = make_jwt(roles=["staff_admin"], sub=str(other))
    resp = client.delete(
        f"/api/v1/vault/secrets/{secret.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Groups


def test_create_group(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    uid = uuid4()
    group = _make_group(uid)
    override_deps["create_group"].return_value = group
    token = make_jwt(roles=["staff_admin"], sub=str(uid))
    resp = client.post(
        "/api/v1/vault/groups",
        json={"name": "Team"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Team"
    override_deps["create_group"].assert_awaited_once()


def test_list_groups_empty(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/vault/groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"data": []}


# ---------------------------------------------------------------------------
# Sharing (ADR-0017)


def test_get_user_pubkey_returns_pubkey(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """GET /vault/users/{id}/pubkey — любой authenticated user."""
    target_uid = uuid4()
    override_deps["get_user_pubkey"].return_value = b"\x01" * 32
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/vault/users/{target_uid}/pubkey",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == str(target_uid)
    assert len(body["x25519_pubkey_b64"]) > 0


def test_get_user_pubkey_404_when_vault_not_setup(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["get_user_pubkey"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/vault/users/{uuid4()}/pubkey",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_get_user_pubkey_requires_auth(client: TestClient) -> None:
    resp = client.get(f"/api/v1/vault/users/{uuid4()}/pubkey")
    assert resp.status_code == 401


def test_add_wraps_success(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """POST /vault/secrets/{id}/wraps — каллер имеет access → 204 + audit."""
    sid = uuid4()
    actor = uuid4()
    new_recipient = uuid4()
    secret_mock = MagicMock(archived_at=None, owner_id=actor, category="infra")
    override_deps["get_secret"].return_value = secret_mock
    override_deps["can_user_access_secret"].return_value = True
    override_deps["add_secret_wraps"].return_value = 1
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.post(
        f"/api/v1/vault/secrets/{sid}/wraps",
        json={
            "wraps": [
                {
                    "user_id": str(new_recipient),
                    "wrapped_key_b64": _b64(b"\xaa" * 48),
                }
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    audit_record_mock.assert_awaited()
    audit_args = audit_record_mock.call_args.kwargs
    assert audit_args["action"] == "vault.share.added"
    assert audit_args["metadata"]["added_count"] == 1


def test_add_wraps_404_no_access(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Caller без access → 404 (anti-enumeration)."""
    sid = uuid4()
    secret_mock = MagicMock(archived_at=None, owner_id=uuid4(), category="x")
    override_deps["get_secret"].return_value = secret_mock
    override_deps["can_user_access_secret"].return_value = False
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/vault/secrets/{sid}/wraps",
        json={
            "wraps": [
                {
                    "user_id": str(uuid4()),
                    "wrapped_key_b64": _b64(b"\xaa" * 48),
                }
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_add_wraps_404_secret_missing(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["get_secret"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/vault/secrets/{uuid4()}/wraps",
        json={
            "wraps": [
                {"user_id": str(uuid4()), "wrapped_key_b64": _b64(b"\xaa" * 48)}
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_remove_wrap_success(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """DELETE wrap — owner-only."""
    sid = uuid4()
    owner = uuid4()
    target = uuid4()
    override_deps["get_secret"].return_value = MagicMock(
        archived_at=None, owner_id=owner, category="x"
    )
    override_deps["remove_secret_wrap"].return_value = True
    token = make_jwt(roles=["staff_admin"], sub=str(owner))
    resp = client.delete(
        f"/api/v1/vault/secrets/{sid}/wraps/{target}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    audit_args = audit_record_mock.call_args.kwargs
    assert audit_args["action"] == "vault.share.revoked"


def test_remove_wrap_403_non_owner(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Non-owner попытка revoke → 403."""
    sid = uuid4()
    owner = uuid4()
    actor = uuid4()
    override_deps["get_secret"].return_value = MagicMock(
        archived_at=None, owner_id=owner, category="x"
    )
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.delete(
        f"/api/v1/vault/secrets/{sid}/wraps/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_remove_wrap_404_no_wrap(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Owner, но wrap не существует → 404."""
    sid = uuid4()
    owner = uuid4()
    override_deps["get_secret"].return_value = MagicMock(
        archived_at=None, owner_id=owner, category="x"
    )
    override_deps["remove_secret_wrap"].return_value = False
    token = make_jwt(roles=["staff_admin"], sub=str(owner))
    resp = client.delete(
        f"/api/v1/vault/secrets/{sid}/wraps/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404

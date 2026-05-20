"""Unit tests для FIDO2 router endpoints (ADR-0022 A)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.vault.fido2 import FIDO2CeremonyError, FIDO2ReplayDetectedError
from src.api.vault.fido2_repository import (
    VaultFIDO2CapacityError,
    VaultFIDO2ChallengeRepository,
    VaultFIDO2Repository,
    get_fido2_challenge_repository,
    get_fido2_repository,
)
from src.api.vault.models import VaultFIDO2Credential


def _make_cred(user_id: Any) -> VaultFIDO2Credential:
    c = VaultFIDO2Credential()
    c.id = uuid4()
    c.user_id = user_id
    c.credential_id = b"\xaa" * 32
    c.public_key = b"\x02" * 64
    c.sign_count = 0
    c.transports = ["usb"]
    c.aaguid = None
    c.nickname = "YubiKey"
    c.created_at = datetime(2026, 5, 20, tzinfo=UTC)
    c.last_used_at = None
    return c


@pytest.fixture
def override_repos() -> Iterator[dict[str, MagicMock]]:
    cred_repo = MagicMock(spec=VaultFIDO2Repository)
    cred_repo.list_by_user = AsyncMock(return_value=[])
    cred_repo.get_by_credential_id = AsyncMock(return_value=None)
    cred_repo.create = AsyncMock()
    cred_repo.delete_by_id = AsyncMock(return_value=False)
    cred_repo.update_sign_count = AsyncMock()

    challenge_repo = MagicMock(spec=VaultFIDO2ChallengeRepository)
    challenge_repo.create = AsyncMock()
    challenge_repo.consume = AsyncMock(return_value=True)

    app.dependency_overrides[get_fido2_repository] = lambda: cred_repo
    app.dependency_overrides[get_fido2_challenge_repository] = lambda: challenge_repo
    yield {"cred": cred_repo, "challenge": challenge_repo}
    app.dependency_overrides.pop(get_fido2_repository, None)
    app.dependency_overrides.pop(get_fido2_challenge_repository, None)


# ---------------------------------------------------------------------------
# register-begin


def test_register_begin_requires_auth(
    client: TestClient,
    override_repos: dict[str, MagicMock],
) -> None:
    resp = client.post("/api/v1/vault/fido2/register-begin")
    assert resp.status_code == 401


def test_register_begin_returns_options(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    with patch(
        "src.api.vault.fido2_router.start_registration",
        new=AsyncMock(return_value={"challenge": "abc", "rp": {"id": "localhost"}}),
    ):
        resp = client.post(
            "/api/v1/vault/fido2/register-begin",
            json={"user_display_name": "Алиса"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["options"]["challenge"] == "abc"


# ---------------------------------------------------------------------------
# register-complete


def test_register_complete_capacity_returns_409(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    with patch(
        "src.api.vault.fido2_router.complete_registration",
        new=AsyncMock(side_effect=VaultFIDO2CapacityError("at cap")),
    ):
        resp = client.post(
            "/api/v1/vault/fido2/register-complete",
            json={"credential": {"rawId": "x", "response": {"clientDataJSON": "y"}}},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 409
    assert "at cap" in resp.json()["detail"]


def test_register_complete_invalid_challenge_returns_400(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    with patch(
        "src.api.vault.fido2_router.complete_registration",
        new=AsyncMock(side_effect=FIDO2CeremonyError("Challenge expired")),
    ):
        resp = client.post(
            "/api/v1/vault/fido2/register-complete",
            json={"credential": {"rawId": "x", "response": {"clientDataJSON": "y"}}},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400


def test_register_complete_happy_path_returns_201(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    user_id = uuid4()
    cred = _make_cred(user_id)
    token = make_jwt(roles=["tenant"], sub=str(user_id))

    with patch(
        "src.api.vault.fido2_router.complete_registration",
        new=AsyncMock(return_value=cred),
    ):
        resp = client.post(
            "/api/v1/vault/fido2/register-complete",
            json={
                "credential": {"rawId": "x", "response": {"clientDataJSON": "y"}},
                "nickname": "YubiKey",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == str(cred.id)
    assert body["nickname"] == "YubiKey"


# ---------------------------------------------------------------------------
# assert-begin / assert-complete


def test_assert_begin_no_keys_returns_400(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    with patch(
        "src.api.vault.fido2_router.start_authentication",
        new=AsyncMock(side_effect=FIDO2CeremonyError("No FIDO2 keys registered for user")),
    ):
        resp = client.post(
            "/api/v1/vault/fido2/assert-begin",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
    assert "No FIDO2 keys" in resp.json()["detail"]


def test_assert_complete_happy_path_returns_verified(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    user_id = uuid4()
    cred = _make_cred(user_id)
    token = make_jwt(roles=["tenant"], sub=str(user_id))

    with patch(
        "src.api.vault.fido2_router.complete_authentication",
        new=AsyncMock(return_value=cred),
    ):
        resp = client.post(
            "/api/v1/vault/fido2/assert-complete",
            json={"credential": {"rawId": "x", "response": {"clientDataJSON": "y"}}},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "verified"}


def test_assert_complete_replay_returns_409(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    with patch(
        "src.api.vault.fido2_router.complete_authentication",
        new=AsyncMock(side_effect=FIDO2ReplayDetectedError("regressed")),
    ):
        resp = client.post(
            "/api/v1/vault/fido2/assert-complete",
            json={"credential": {"rawId": "x", "response": {"clientDataJSON": "y"}}},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 409


def test_assert_complete_invalid_signature_returns_400(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    with patch(
        "src.api.vault.fido2_router.complete_authentication",
        new=AsyncMock(side_effect=FIDO2CeremonyError("Invalid assertion")),
    ):
        resp = client.post(
            "/api/v1/vault/fido2/assert-complete",
            json={"credential": {"rawId": "x", "response": {"clientDataJSON": "y"}}},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# List / delete


def test_list_credentials_returns_user_keys(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    user_id = uuid4()
    cred = _make_cred(user_id)
    override_repos["cred"].list_by_user = AsyncMock(return_value=[cred])

    token = make_jwt(roles=["tenant"], sub=str(user_id))
    resp = client.get(
        "/api/v1/vault/fido2/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == str(cred.id)
    assert body["data"][0]["nickname"] == "YubiKey"
    assert body["data"][0]["transports"] == ["usb"]


def test_delete_credential_404_when_not_owned(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    override_repos["cred"].delete_by_id = AsyncMock(return_value=False)
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/vault/fido2/credentials/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_delete_credential_returns_204(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    override_repos["cred"].delete_by_id = AsyncMock(return_value=True)
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/vault/fido2/credentials/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204


def test_register_begin_requires_valid_uuid_sub(
    client: TestClient,
    override_repos: dict[str, MagicMock],
    make_jwt: Callable[..., str],
) -> None:
    """sub claim should be UUID — non-UUID → 401."""
    token = make_jwt(roles=["tenant"], sub="not-a-uuid")
    resp = client.post(
        "/api/v1/vault/fido2/register-begin",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401

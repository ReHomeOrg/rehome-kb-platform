"""Unit tests для FIDO2 ceremony service (ADR-0022 A).

py_webauthn-side crypto verification is mocked; tests focus on
orchestration: challenge persistence + consumption, repo interactions,
error mapping.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.api.vault.fido2 import (
    FIDO2CeremonyError,
    FIDO2ReplayDetectedError,
    complete_authentication,
    complete_registration,
    start_authentication,
    start_registration,
)
from src.api.vault.fido2_repository import VaultFIDO2CapacityError
from src.api.vault.models import VaultFIDO2Credential


def _settings() -> Any:
    s = MagicMock()
    s.webauthn_rp_id = "localhost"
    s.webauthn_rp_name = "Test"
    s.webauthn_user_verification = "preferred"
    s.webauthn_origin_list = ("http://localhost:3000",)
    return s


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _client_data_with_challenge(challenge: bytes) -> str:
    """Build minimal clientDataJSON base64url containing given challenge."""
    payload = {"challenge": _b64url(challenge), "origin": "http://localhost:3000"}
    return _b64url(json.dumps(payload).encode("utf-8"))


def _make_credential(challenge: bytes, raw_id: bytes = b"\xaa" * 32) -> dict[str, Any]:
    return {
        "rawId": _b64url(raw_id),
        "response": {
            "clientDataJSON": _client_data_with_challenge(challenge),
            "transports": ["usb"],
        },
    }


def _make_stored_cred(user_id: Any, raw_id: bytes = b"\xaa" * 32) -> VaultFIDO2Credential:
    c = VaultFIDO2Credential()
    c.id = uuid4()
    c.user_id = user_id
    c.credential_id = raw_id
    c.public_key = b"\x02" * 64
    c.sign_count = 5
    c.transports = ["usb"]
    c.aaguid = None
    c.nickname = None
    return c


# ---------------------------------------------------------------------------
# start_registration


@pytest.mark.asyncio
async def test_start_registration_persists_challenge_and_returns_options() -> None:
    user_id = uuid4()
    cred_repo = MagicMock()
    cred_repo.list_by_user = AsyncMock(return_value=[])
    challenge_repo = MagicMock()
    challenge_repo.create = AsyncMock()

    options = await start_registration(
        user_id=user_id,
        user_name="alice",
        user_display_name=None,
        cred_repo=cred_repo,
        challenge_repo=challenge_repo,
        settings=_settings(),
    )
    assert "challenge" in options
    challenge_repo.create.assert_awaited_once()
    kw = challenge_repo.create.call_args.kwargs
    assert kw["user_id"] == user_id
    assert kw["ceremony"] == "registration"
    assert isinstance(kw["challenge"], bytes)


@pytest.mark.asyncio
async def test_start_registration_excludes_existing_credentials() -> None:
    """exclude_credentials prevents duplicate registration."""
    user_id = uuid4()
    existing = _make_stored_cred(user_id, raw_id=b"\x11" * 32)
    cred_repo = MagicMock()
    cred_repo.list_by_user = AsyncMock(return_value=[existing])
    challenge_repo = MagicMock()
    challenge_repo.create = AsyncMock()

    options = await start_registration(
        user_id=user_id,
        user_name="alice",
        user_display_name=None,
        cred_repo=cred_repo,
        challenge_repo=challenge_repo,
        settings=_settings(),
    )
    # Existing credential should appear в excludeCredentials list.
    exclude_ids = [c["id"] for c in options.get("excludeCredentials", [])]
    assert _b64url(b"\x11" * 32) in exclude_ids


# ---------------------------------------------------------------------------
# complete_registration


@pytest.mark.asyncio
async def test_complete_registration_rejects_invalid_challenge() -> None:
    user_id = uuid4()
    cred_repo = MagicMock()
    challenge_repo = MagicMock()
    challenge_repo.consume = AsyncMock(return_value=False)

    challenge = b"\xcc" * 32
    with pytest.raises(FIDO2CeremonyError, match="Challenge expired"):
        await complete_registration(
            user_id=user_id,
            credential=_make_credential(challenge),
            nickname=None,
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=_settings(),
        )


@pytest.mark.asyncio
async def test_complete_registration_persists_credential_on_success() -> None:
    user_id = uuid4()
    challenge = b"\xcc" * 32

    cred_repo = MagicMock()
    cred_repo.create = AsyncMock(return_value=_make_stored_cred(user_id))
    challenge_repo = MagicMock()
    challenge_repo.consume = AsyncMock(return_value=True)

    verified = MagicMock(
        credential_id=b"\xaa" * 32,
        credential_public_key=b"\x02" * 64,
        sign_count=0,
        aaguid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    with patch("src.api.vault.fido2.verify_registration_response", return_value=verified):
        cred = await complete_registration(
            user_id=user_id,
            credential=_make_credential(challenge),
            nickname="YubiKey",
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=_settings(),
        )

    assert cred is not None
    cred_repo.create.assert_awaited_once()
    kwargs = cred_repo.create.call_args.kwargs
    assert kwargs["user_id"] == user_id
    assert kwargs["credential_id"] == b"\xaa" * 32
    assert kwargs["nickname"] == "YubiKey"
    assert kwargs["transports"] == ["usb"]


@pytest.mark.asyncio
async def test_complete_registration_propagates_capacity_error() -> None:
    user_id = uuid4()
    challenge = b"\xcc" * 32

    cred_repo = MagicMock()
    cred_repo.create = AsyncMock(side_effect=VaultFIDO2CapacityError("at cap"))
    challenge_repo = MagicMock()
    challenge_repo.consume = AsyncMock(return_value=True)

    verified = MagicMock(
        credential_id=b"\xaa" * 32,
        credential_public_key=b"\x02" * 64,
        sign_count=0,
        aaguid=None,
    )

    with (
        patch("src.api.vault.fido2.verify_registration_response", return_value=verified),
        pytest.raises(VaultFIDO2CapacityError),
    ):
        await complete_registration(
            user_id=user_id,
            credential=_make_credential(challenge),
            nickname=None,
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=_settings(),
        )


# ---------------------------------------------------------------------------
# start_authentication


@pytest.mark.asyncio
async def test_start_authentication_rejects_user_without_keys() -> None:
    cred_repo = MagicMock()
    cred_repo.list_by_user = AsyncMock(return_value=[])
    challenge_repo = MagicMock()

    with pytest.raises(FIDO2CeremonyError, match="No FIDO2 keys"):
        await start_authentication(
            user_id=uuid4(),
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=_settings(),
        )


@pytest.mark.asyncio
async def test_start_authentication_persists_challenge() -> None:
    user_id = uuid4()
    cred_repo = MagicMock()
    cred_repo.list_by_user = AsyncMock(return_value=[_make_stored_cred(user_id)])
    challenge_repo = MagicMock()
    challenge_repo.create = AsyncMock()

    options = await start_authentication(
        user_id=user_id,
        cred_repo=cred_repo,
        challenge_repo=challenge_repo,
        settings=_settings(),
    )
    assert "challenge" in options
    challenge_repo.create.assert_awaited_once()
    assert challenge_repo.create.call_args.kwargs["ceremony"] == "authentication"


# ---------------------------------------------------------------------------
# complete_authentication


@pytest.mark.asyncio
async def test_complete_authentication_rejects_unregistered_credential() -> None:
    """Если credential_id из response не stored — 400."""
    user_id = uuid4()
    challenge = b"\xcc" * 32

    cred_repo = MagicMock()
    cred_repo.get_by_credential_id = AsyncMock(return_value=None)
    challenge_repo = MagicMock()
    challenge_repo.consume = AsyncMock(return_value=True)

    with pytest.raises(FIDO2CeremonyError, match="not registered"):
        await complete_authentication(
            user_id=user_id,
            credential=_make_credential(challenge),
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=_settings(),
        )


@pytest.mark.asyncio
async def test_complete_authentication_rejects_cross_user_credential() -> None:
    """Stored credential exists но user_id mismatch."""
    user_id = uuid4()
    other_user = uuid4()
    challenge = b"\xcc" * 32

    cred_repo = MagicMock()
    cred_repo.get_by_credential_id = AsyncMock(return_value=_make_stored_cred(other_user))
    challenge_repo = MagicMock()
    challenge_repo.consume = AsyncMock(return_value=True)

    with pytest.raises(FIDO2CeremonyError, match="not registered"):
        await complete_authentication(
            user_id=user_id,
            credential=_make_credential(challenge),
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=_settings(),
        )


@pytest.mark.asyncio
async def test_complete_authentication_detects_sign_count_regression() -> None:
    """new_sign_count < stored → FIDO2ReplayDetectedError."""
    user_id = uuid4()
    challenge = b"\xcc" * 32
    stored = _make_stored_cred(user_id)
    stored.sign_count = 100

    cred_repo = MagicMock()
    cred_repo.get_by_credential_id = AsyncMock(return_value=stored)
    cred_repo.update_sign_count = AsyncMock()
    challenge_repo = MagicMock()
    challenge_repo.consume = AsyncMock(return_value=True)

    verified = MagicMock(new_sign_count=50)

    with (
        patch("src.api.vault.fido2.verify_authentication_response", return_value=verified),
        pytest.raises(FIDO2ReplayDetectedError, match="regressed"),
    ):
        await complete_authentication(
            user_id=user_id,
            credential=_make_credential(challenge),
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=_settings(),
        )


@pytest.mark.asyncio
async def test_complete_authentication_happy_path_bumps_sign_count() -> None:
    user_id = uuid4()
    challenge = b"\xcc" * 32
    stored = _make_stored_cred(user_id)
    stored.sign_count = 5

    cred_repo = MagicMock()
    cred_repo.get_by_credential_id = AsyncMock(return_value=stored)
    cred_repo.update_sign_count = AsyncMock()
    challenge_repo = MagicMock()
    challenge_repo.consume = AsyncMock(return_value=True)

    verified = MagicMock(new_sign_count=6)

    with patch("src.api.vault.fido2.verify_authentication_response", return_value=verified):
        result = await complete_authentication(
            user_id=user_id,
            credential=_make_credential(challenge),
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=_settings(),
        )

    assert result is stored
    cred_repo.update_sign_count.assert_awaited_once_with(stored.id, 6)

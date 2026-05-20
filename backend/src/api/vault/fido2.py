"""FIDO2 / WebAuthn ceremony service (ADR-0022 A).

4 entry points:
- `start_registration` — generate registration options + persist challenge.
- `complete_registration` — verify attestation + store credential.
- `start_authentication` — generate assertion options + persist challenge.
- `complete_authentication` — verify assertion + bump sign_count.

Per CLAUDE.md: external library = py_webauthn (MIT, self-hosted, no
network). All crypto verification local. ФЗ-152 OK (no plaintext PII в
ceremony — public keys only).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from src.api.config import Settings
from src.api.vault.fido2_repository import (
    VaultFIDO2CapacityError,
    VaultFIDO2ChallengeRepository,
    VaultFIDO2Repository,
)
from src.api.vault.models import VaultFIDO2Credential

logger = logging.getLogger(__name__)


class FIDO2CeremonyError(Exception):
    """Generic ceremony failure (invalid challenge / signature / expired)."""


class FIDO2ReplayDetectedError(FIDO2CeremonyError):
    """sign_count from authenticator <= stored — possible cloned credential."""


def _user_verification(settings: Settings) -> UserVerificationRequirement:
    raw = settings.webauthn_user_verification
    return UserVerificationRequirement(raw)


async def start_registration(
    *,
    user_id: UUID,
    user_name: str,
    user_display_name: str | None,
    cred_repo: VaultFIDO2Repository,
    challenge_repo: VaultFIDO2ChallengeRepository,
    settings: Settings,
) -> dict[str, Any]:
    """Generate PublicKeyCredentialCreationOptions + persist challenge.

    Returns options as plain dict (caller JSON-serializes); challenge
    encoded base64url для browser consumption.
    """
    existing = await cred_repo.list_by_user(user_id)
    exclude = [PublicKeyCredentialDescriptor(id=c.credential_id, transports=None) for c in existing]

    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_name=user_name,
        user_id=str(user_id).encode("utf-8"),
        user_display_name=user_display_name or user_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=_user_verification(settings),
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
        exclude_credentials=exclude,
    )
    await challenge_repo.create(
        challenge=options.challenge,
        user_id=user_id,
        ceremony="registration",
    )
    return _options_to_dict(options)


async def complete_registration(
    *,
    user_id: UUID,
    credential: dict[str, Any],
    nickname: str | None,
    cred_repo: VaultFIDO2Repository,
    challenge_repo: VaultFIDO2ChallengeRepository,
    settings: Settings,
) -> VaultFIDO2Credential:
    """Verify attestation, persist credential row. Raises FIDO2CeremonyError
    on invalid challenge / signature / expired."""
    raw_challenge = _decode_b64url(credential["response"]["clientDataJSON"], pluck="challenge")
    valid = await challenge_repo.consume(
        challenge=raw_challenge,
        user_id=user_id,
        ceremony="registration",
    )
    if not valid:
        raise FIDO2CeremonyError("Challenge expired or not issued for this user")

    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=raw_challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=list(settings.webauthn_origin_list),
            require_user_verification=settings.webauthn_user_verification == "required",
        )
    except InvalidRegistrationResponse as exc:
        raise FIDO2CeremonyError(f"Invalid attestation: {exc}") from exc

    transports = credential.get("response", {}).get("transports") or []
    try:
        row = await cred_repo.create(
            user_id=user_id,
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            transports=list(transports),
            aaguid=verified.aaguid.encode("utf-8") if verified.aaguid else None,
            nickname=nickname,
            sign_count=verified.sign_count,
        )
    except VaultFIDO2CapacityError:
        raise
    return row


async def start_authentication(
    *,
    user_id: UUID,
    cred_repo: VaultFIDO2Repository,
    challenge_repo: VaultFIDO2ChallengeRepository,
    settings: Settings,
) -> dict[str, Any]:
    """Generate PublicKeyCredentialRequestOptions + persist challenge."""
    creds = await cred_repo.list_by_user(user_id)
    if not creds:
        raise FIDO2CeremonyError("No FIDO2 keys registered for user")
    allow = [
        PublicKeyCredentialDescriptor(
            id=c.credential_id,
            transports=None,
        )
        for c in creds
    ]
    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=allow,
        user_verification=_user_verification(settings),
    )
    await challenge_repo.create(
        challenge=options.challenge,
        user_id=user_id,
        ceremony="authentication",
    )
    return _options_to_dict(options)


async def complete_authentication(
    *,
    user_id: UUID,
    credential: dict[str, Any],
    cred_repo: VaultFIDO2Repository,
    challenge_repo: VaultFIDO2ChallengeRepository,
    settings: Settings,
) -> VaultFIDO2Credential:
    """Verify assertion signature + update sign_count.

    Raises FIDO2ReplayDetectedError if new sign_count <= stored
    (cloned credential indicator — caller should record security_incident).
    """
    raw_challenge = _decode_b64url(credential["response"]["clientDataJSON"], pluck="challenge")
    valid = await challenge_repo.consume(
        challenge=raw_challenge,
        user_id=user_id,
        ceremony="authentication",
    )
    if not valid:
        raise FIDO2CeremonyError("Challenge expired or not issued for this user")

    raw_credential_id = _decode_b64url_raw(credential["rawId"])
    stored = await cred_repo.get_by_credential_id(raw_credential_id)
    if stored is None or stored.user_id != user_id:
        raise FIDO2CeremonyError("Credential not registered for this user")

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=raw_challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=list(settings.webauthn_origin_list),
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
            require_user_verification=settings.webauthn_user_verification == "required",
        )
    except InvalidAuthenticationResponse as exc:
        raise FIDO2CeremonyError(f"Invalid assertion: {exc}") from exc

    # Replay-detection: новый count должен быть строго больше stored
    # (single-credential authenticators) или = stored (multi-device passkeys
    # которые не bump counter). py_webauthn делает свой check; здесь
    # дополнительный guard на nonzero counters.
    if verified.new_sign_count and verified.new_sign_count < stored.sign_count:
        raise FIDO2ReplayDetectedError(
            f"sign_count regressed ({verified.new_sign_count} < {stored.sign_count})"
        )

    await cred_repo.update_sign_count(stored.id, verified.new_sign_count)
    return stored


# ---------------------------------------------------------------------------
# Helpers


def _options_to_dict(options: Any) -> dict[str, Any]:
    """Convert py_webauthn dataclass options → plain dict (browser-ready).

    py_webauthn provides `options_to_json` but returns string; we want
    dict для FastAPI response_model.
    """
    import json as _json

    from webauthn.helpers import options_to_json

    return dict(_json.loads(options_to_json(options)))


def _decode_b64url_raw(data: str) -> bytes:
    """Decode base64url string (browser-encoded credentialId / rawId) →
    bytes. WebAuthn uses base64url без padding."""
    import base64

    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _decode_b64url(client_data_json_b64: str, *, pluck: str) -> bytes:
    """Decode clientDataJSON (base64url) + pluck specific field (e.g.
    challenge) → raw bytes."""
    import base64
    import json as _json

    raw = _decode_b64url_raw(client_data_json_b64)
    payload = _json.loads(raw.decode("utf-8"))
    field_b64 = payload[pluck]
    padding = "=" * (-len(field_b64) % 4)
    return base64.urlsafe_b64decode(field_b64 + padding)


__all__ = [
    "FIDO2CeremonyError",
    "FIDO2ReplayDetectedError",
    "complete_authentication",
    "complete_registration",
    "start_authentication",
    "start_registration",
]

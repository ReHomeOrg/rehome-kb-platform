"""FIDO2 / WebAuthn ceremony endpoints (ADR-0022 A).

6 endpoints:
- POST /vault/fido2/register-begin — generate registration options.
- POST /vault/fido2/register-complete — verify + persist credential.
- POST /vault/fido2/assert-begin — generate authentication options.
- POST /vault/fido2/assert-complete — verify + bump sign_count.
- GET /vault/fido2/credentials — list user's registered keys.
- DELETE /vault/fido2/credentials/{id} — revoke specific key.

Auth: `require_authenticated` (Keycloak JWT). `sub` claim → user_id.
TOTP-grandfathered users могут add FIDO2 параллельно (ADR-0022 A
migration UX).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit.actions import (
    ACTION_VAULT_FIDO2_ASSERT_FAILED,
    ACTION_VAULT_FIDO2_ASSERT_SUCCESS,
    ACTION_VAULT_FIDO2_REGISTERED,
    ACTION_VAULT_FIDO2_REVOKED,
    RESOURCE_VAULT_USER,
)
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.auth.dependency import require_authenticated
from src.api.config import Settings, get_settings
from src.api.db import get_session
from src.api.vault.fido2 import (
    FIDO2CeremonyError,
    FIDO2ReplayDetectedError,
    complete_authentication,
    complete_registration,
    start_authentication,
    start_registration,
)
from src.api.vault.fido2_repository import (
    VaultFIDO2CapacityError,
    VaultFIDO2ChallengeRepository,
    VaultFIDO2Repository,
    get_fido2_challenge_repository,
    get_fido2_repository,
)
from src.api.vault.fido2_schemas import (
    FIDO2AssertBeginResponse,
    FIDO2AssertCompleteInput,
    FIDO2CredentialListResponse,
    FIDO2CredentialView,
    FIDO2RegisterBeginInput,
    FIDO2RegisterBeginResponse,
    FIDO2RegisterCompleteInput,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vault/fido2", tags=["Vault"])


def _user_id_from_claims(claims: dict[str, Any]) -> UUID:
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Missing sub claim")
    try:
        return UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid sub claim") from exc


def _user_name_from_claims(claims: dict[str, Any]) -> str:
    """preferred_username от Keycloak → WebAuthn user.name."""
    raw = claims.get("preferred_username") or claims.get("sub", "unknown")
    return str(raw)


# ---------------------------------------------------------------------------
# Registration


@router.post(
    "/register-begin",
    response_model=FIDO2RegisterBeginResponse,
    summary="Начать FIDO2 registration ceremony",
    responses={
        200: {"description": "Options сгенерированы"},
        401: {"description": "Не аутентифицирован"},
        409: {"description": "Превышен лимит ключей (MAX_KEYS_PER_USER)"},
    },
)
async def register_begin(
    payload: FIDO2RegisterBeginInput | None = None,
    claims: dict[str, Any] = Depends(require_authenticated),
    cred_repo: VaultFIDO2Repository = Depends(get_fido2_repository),
    challenge_repo: VaultFIDO2ChallengeRepository = Depends(get_fido2_challenge_repository),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FIDO2RegisterBeginResponse:
    user_id = _user_id_from_claims(claims)
    body = payload or FIDO2RegisterBeginInput()

    options = await start_registration(
        user_id=user_id,
        user_name=_user_name_from_claims(claims),
        user_display_name=body.user_display_name,
        cred_repo=cred_repo,
        challenge_repo=challenge_repo,
        settings=settings,
    )
    await session.commit()
    return FIDO2RegisterBeginResponse(options=options)


@router.post(
    "/register-complete",
    summary="Завершить FIDO2 registration ceremony",
    responses={
        201: {"description": "Credential зарегистрирован"},
        400: {"description": "Невалидный challenge / attestation"},
        401: {"description": "Не аутентифицирован"},
        409: {"description": "Превышен лимит ключей"},
    },
    status_code=201,
)
async def register_complete(
    payload: FIDO2RegisterCompleteInput,
    claims: dict[str, Any] = Depends(require_authenticated),
    cred_repo: VaultFIDO2Repository = Depends(get_fido2_repository),
    challenge_repo: VaultFIDO2ChallengeRepository = Depends(get_fido2_challenge_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FIDO2CredentialView:
    user_id = _user_id_from_claims(claims)
    try:
        cred = await complete_registration(
            user_id=user_id,
            credential=payload.credential,
            nickname=payload.nickname,
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=settings,
        )
    except VaultFIDO2CapacityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FIDO2CeremonyError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await audit_repo.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_FIDO2_REGISTERED,
        resource_type=RESOURCE_VAULT_USER,
        resource_id=str(cred.id),
        metadata={"transports": cred.transports, "nickname": cred.nickname},
    )
    await session.commit()
    return FIDO2CredentialView.model_validate(cred)


# ---------------------------------------------------------------------------
# Authentication (assertion)


@router.post(
    "/assert-begin",
    response_model=FIDO2AssertBeginResponse,
    summary="Начать FIDO2 unlock ceremony",
    responses={
        200: {"description": "Options сгенерированы"},
        400: {"description": "У пользователя нет registered keys"},
        401: {"description": "Не аутентифицирован"},
    },
)
async def assert_begin(
    claims: dict[str, Any] = Depends(require_authenticated),
    cred_repo: VaultFIDO2Repository = Depends(get_fido2_repository),
    challenge_repo: VaultFIDO2ChallengeRepository = Depends(get_fido2_challenge_repository),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FIDO2AssertBeginResponse:
    user_id = _user_id_from_claims(claims)
    try:
        options = await start_authentication(
            user_id=user_id,
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=settings,
        )
    except FIDO2CeremonyError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    return FIDO2AssertBeginResponse(options=options)


@router.post(
    "/assert-complete",
    summary="Завершить FIDO2 unlock ceremony",
    responses={
        200: {"description": "Подпись подтверждена"},
        400: {"description": "Невалидный challenge / signature"},
        401: {"description": "Не аутентифицирован"},
        409: {"description": "Replay detected (sign_count regression)"},
    },
)
async def assert_complete(
    payload: FIDO2AssertCompleteInput,
    claims: dict[str, Any] = Depends(require_authenticated),
    cred_repo: VaultFIDO2Repository = Depends(get_fido2_repository),
    challenge_repo: VaultFIDO2ChallengeRepository = Depends(get_fido2_challenge_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    user_id = _user_id_from_claims(claims)
    try:
        cred = await complete_authentication(
            user_id=user_id,
            credential=payload.credential,
            cred_repo=cred_repo,
            challenge_repo=challenge_repo,
            settings=settings,
        )
    except FIDO2ReplayDetectedError as exc:
        # Auditable security signal — log explicit failure.
        await session.rollback()
        await audit_repo.record(
            actor_sub=str(user_id),
            action=ACTION_VAULT_FIDO2_ASSERT_FAILED,
            resource_type=RESOURCE_VAULT_USER,
            resource_id=str(user_id),
            metadata={"reason": "replay_detected"},
        )
        await session.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FIDO2CeremonyError as exc:
        await session.rollback()
        await audit_repo.record(
            actor_sub=str(user_id),
            action=ACTION_VAULT_FIDO2_ASSERT_FAILED,
            resource_type=RESOURCE_VAULT_USER,
            resource_id=str(user_id),
            metadata={"reason": "ceremony_error"},
        )
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await audit_repo.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_FIDO2_ASSERT_SUCCESS,
        resource_type=RESOURCE_VAULT_USER,
        resource_id=str(cred.id),
        metadata={},
    )
    await session.commit()
    return {"status": "verified"}


# ---------------------------------------------------------------------------
# List / delete credentials


@router.get(
    "/credentials",
    response_model=FIDO2CredentialListResponse,
    summary="Список registered FIDO2 keys",
)
async def list_credentials(
    claims: dict[str, Any] = Depends(require_authenticated),
    cred_repo: VaultFIDO2Repository = Depends(get_fido2_repository),
) -> FIDO2CredentialListResponse:
    user_id = _user_id_from_claims(claims)
    rows = await cred_repo.list_by_user(user_id)
    return FIDO2CredentialListResponse(data=[FIDO2CredentialView.model_validate(r) for r in rows])


@router.delete(
    "/credentials/{credential_id}",
    status_code=204,
    summary="Удалить FIDO2 key",
    responses={
        204: {"description": "Удалено"},
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Не найдено или не принадлежит пользователю"},
    },
)
async def delete_credential(
    credential_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    cred_repo: VaultFIDO2Repository = Depends(get_fido2_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> None:
    user_id = _user_id_from_claims(claims)
    deleted = await cred_repo.delete_by_id(credential_id, user_id=user_id)
    if not deleted:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Credential not found")
    await audit_repo.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_FIDO2_REVOKED,
        resource_type=RESOURCE_VAULT_USER,
        resource_id=str(credential_id),
        metadata={},
    )
    await session.commit()


__all__ = ["router"]

"""Emergency access endpoints (ADR-0021 A).

2 endpoints:
- POST /api/v1/vault/setup-escrow (vault owner) — stores client-built
  escrow_wrap blob. Subsequent emergency unlock возможно.
- POST /api/v1/admin/vault/emergency-unlock (staff_admin + LEGAL) —
  records event (audit + security_incident + log row) + returns
  encrypted key material для client-side ceremony decryption.

RBAC:
- setup-escrow: vault owner only (self).
- emergency-unlock: staff_admin scope (STAFF + LEGAL) per ADR-0011.

Per ADR-0021 §approve note: backend никогда не видит shares; combine +
decrypt происходит в admin browser (PR 2 frontend).
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit.actions import ACTION_VAULT_ESCROW_SETUP, RESOURCE_VAULT_USER
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.db import get_session
from src.api.vault.emergency_repository import (
    VaultEmergencyRepository,
    get_emergency_repository,
)
from src.api.vault.emergency_schemas import (
    VaultEmergencyPayload,
    VaultEmergencyUnlockInput,
    VaultEmergencyUnlockResponse,
    VaultSetupEscrowInput,
    VaultSetupEscrowResponse,
)
from src.api.vault.emergency_service import (
    record_emergency_unlock,
    severity_for_reason,
)
from src.api.vault.repository import VaultRepository, get_vault_repository

logger = logging.getLogger(__name__)

# Separate router prefix per endpoint (different RBAC + path patterns).
owner_router = APIRouter(prefix="/vault", tags=["Vault"])
admin_router = APIRouter(prefix="/admin/vault", tags=["Admin"])


def _user_id_from_claims(claims: dict[str, Any]) -> UUID:
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Missing sub claim")
    try:
        return UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid sub claim") from exc


def _require_staff_admin(access_levels: frozenset[AccessLevel]) -> None:
    """Emergency unlock — staff_admin scope (STAFF + LEGAL) per ADR-0011."""
    if not (AccessLevel.STAFF in access_levels and AccessLevel.LEGAL in access_levels):
        raise HTTPException(status_code=403, detail="Требуется staff_admin scope")


def _decode_b64(field: str, value: str, max_bytes: int) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field}: invalid base64") from exc
    if len(raw) > max_bytes:
        raise HTTPException(status_code=422, detail=f"{field}: max {max_bytes} bytes")
    return raw


# ---------------------------------------------------------------------------
# Owner: setup-escrow


@owner_router.post(
    "/setup-escrow",
    response_model=VaultSetupEscrowResponse,
    summary="Установить escrow_wrap для emergency access",
    responses={
        200: {"description": "Escrow ceremony recorded"},
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Vault не setup'нут (run /vault/setup first)"},
        422: {"description": "Невалидный escrow_wrap_b64"},
    },
)
async def setup_escrow(
    payload: VaultSetupEscrowInput,
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultSetupEscrowResponse:
    """Vault owner stores `escrow_wrap` blob — AES-GCM(KEK, escrow_key)
    client-built. Backend treats opaque; никогда не видит escrow_key.

    Idempotent: повторный вызов перезаписывает (rotation flow). Зашифровано
    pod новым escrow_key client должен напечатать новые envelopes + уничтожить
    старые.
    """
    user_id = _user_id_from_claims(claims)
    escrow_wrap = _decode_b64("escrow_wrap_b64", payload.escrow_wrap_b64, max_bytes=512)

    updated = await repo.set_escrow_wrap(user_id, escrow_wrap)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="Vault не setup'нут — call POST /vault/setup first",
        )

    await audit_repo.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_ESCROW_SETUP,
        resource_type=RESOURCE_VAULT_USER,
        resource_id=str(user_id),
        metadata={"escrow_wrap_bytes": len(escrow_wrap)},
    )
    await session.commit()
    return VaultSetupEscrowResponse(has_escrow=True)


# ---------------------------------------------------------------------------
# Admin: emergency-unlock


@admin_router.post(
    "/emergency-unlock",
    response_model=VaultEmergencyUnlockResponse,
    summary="Emergency unlock vault target user (staff_admin)",
    responses={
        200: {"description": "Event recorded + key material returned"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope (STAFF + LEGAL)"},
        404: {"description": "Target user vault не setup'нут или нет escrow"},
        422: {"description": "Невалидный reason_category или reason_text"},
    },
)
async def emergency_unlock(
    payload: VaultEmergencyUnlockInput,
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    vault_repo: VaultRepository = Depends(get_vault_repository),
    emergency_repo: VaultEmergencyRepository = Depends(get_emergency_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultEmergencyUnlockResponse:
    """Admin (директор / юрист — staff_admin scope) records emergency unlock
    event + retrieves target user's encrypted key material.

    Backend никогда не видит shares — client (admin browser) combines
    локально + decrypts. Endpoint только бухгалтерия (audit/incident/log) +
    payload exposure.
    """
    _require_staff_admin(access_levels)
    requested_by = str(claims.get("sub", "unknown"))

    user = await vault_repo.get_user(payload.target_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Target user vault не setup'нут")
    if user.escrow_wrap is None:
        raise HTTPException(
            status_code=404,
            detail="Target user не setup'нул escrow ceremony — recovery невозможна",
        )

    log_row = await record_emergency_unlock(
        target_user_id=payload.target_user_id,
        requested_by=requested_by,
        reason_category=payload.reason_category,
        reason_text=payload.reason_text,
        emergency_repo=emergency_repo,
        audit_repo=audit_repo,
        session=session,
    )

    payload_resp = VaultEmergencyPayload(
        escrow_wrap_b64=base64.b64encode(user.escrow_wrap).decode("ascii"),
        encrypted_x25519_privkey_b64=base64.b64encode(user.encrypted_x25519_privkey).decode(
            "ascii"
        ),
        x25519_pubkey_b64=base64.b64encode(user.x25519_pubkey).decode("ascii"),
        argon_salt_b64=base64.b64encode(user.argon_salt).decode("ascii"),
    )

    await session.commit()
    assert log_row.security_incident_id is not None
    return VaultEmergencyUnlockResponse(
        unlock_log_id=log_row.id,
        security_incident_id=log_row.security_incident_id,
        rkn_notify_required=log_row.rkn_notify_required,
        severity=severity_for_reason(payload.reason_category),
        created_at=log_row.created_at,
        vault=payload_resp,
    )


__all__ = ["admin_router", "owner_router"]

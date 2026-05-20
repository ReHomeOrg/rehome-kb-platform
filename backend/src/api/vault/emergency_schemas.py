"""Pydantic schemas для emergency access endpoints (ADR-0021 A)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Synced with models.EMERGENCY_REASON_CATEGORIES + migration CHECK.
EmergencyReasonCategory = Literal[
    "incident",
    "legal_order",
    "employee_departure",
    "forensic_audit",
    "password_lost",
]


# ---------------------------------------------------------------------------
# Setup escrow (vault owner)


class VaultSetupEscrowInput(BaseModel):
    """POST /vault/setup-escrow — owner stores client-built escrow_wrap.

    `escrow_wrap_b64` — AES-GCM(KEK, escrow_key) blob, client-generated.
    Backend opaque.
    """

    model_config = ConfigDict(extra="forbid")

    escrow_wrap_b64: str = Field(min_length=1, max_length=1024)


class VaultSetupEscrowResponse(BaseModel):
    """Confirms escrow setup."""

    has_escrow: bool


# ---------------------------------------------------------------------------
# Emergency unlock (admin)


class VaultEmergencyUnlockInput(BaseModel):
    """POST /admin/vault/emergency-unlock — admin records event + retrieves
    encrypted vault payload.

    Note: actual share combine + decrypt happens client-side (ADR-0021 §
    approve note «zero-knowledge preserved»). Backend never sees shares.
    """

    model_config = ConfigDict(extra="forbid")

    target_user_id: UUID
    reason_category: EmergencyReasonCategory
    reason_text: str = Field(min_length=10, max_length=2000)


class VaultEmergencyPayload(BaseModel):
    """Encrypted key material for admin's client-side recovery (PR 1 scope).

    Client combines 2 shares локально → derives KEK via AES-GCM(escrow_wrap) →
    decrypts encrypted_x25519_privkey → can then decrypt wraps obtained
    via subsequent admin endpoints (PR 2). Per-secret dump endpoint —
    separate PR.
    """

    escrow_wrap_b64: str
    encrypted_x25519_privkey_b64: str
    x25519_pubkey_b64: str
    argon_salt_b64: str


class VaultEmergencyUnlockResponse(BaseModel):
    """Audit + payload return shape."""

    unlock_log_id: UUID
    security_incident_id: UUID
    rkn_notify_required: bool
    severity: str
    created_at: datetime
    vault: VaultEmergencyPayload


__all__ = [
    "EmergencyReasonCategory",
    "VaultEmergencyPayload",
    "VaultEmergencyUnlockInput",
    "VaultEmergencyUnlockResponse",
    "VaultSetupEscrowInput",
    "VaultSetupEscrowResponse",
]

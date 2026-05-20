"""Pydantic schemas для FIDO2 ceremony endpoints (ADR-0022 A)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Register


class FIDO2RegisterBeginInput(BaseModel):
    """POST /vault/fido2/register-begin body (optional nickname hint)."""

    model_config = ConfigDict(extra="forbid")

    nickname: str | None = Field(default=None, max_length=100)
    user_display_name: str | None = Field(default=None, max_length=100)


class FIDO2RegisterBeginResponse(BaseModel):
    """Returns PublicKeyCredentialCreationOptions (JSON-serialised от
    py_webauthn). Browser passes verbatim в `navigator.credentials.create`."""

    options: dict[str, Any]


class FIDO2RegisterCompleteInput(BaseModel):
    """POST /vault/fido2/register-complete — browser-returned
    AttestationResponse + optional nickname."""

    model_config = ConfigDict(extra="forbid")

    credential: dict[str, Any]
    nickname: str | None = Field(default=None, max_length=100)


# ---------------------------------------------------------------------------
# Assert (authentication)


class FIDO2AssertBeginResponse(BaseModel):
    """PublicKeyCredentialRequestOptions для unlock ceremony."""

    options: dict[str, Any]


class FIDO2AssertCompleteInput(BaseModel):
    """POST /vault/fido2/assert-complete — browser-returned AuthenticationResponse."""

    model_config = ConfigDict(extra="forbid")

    credential: dict[str, Any]


# ---------------------------------------------------------------------------
# Credentials list / delete


class FIDO2CredentialView(BaseModel):
    """Per-credential metadata exposed для `/vault/fido2/credentials` UI."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nickname: str | None
    created_at: datetime
    last_used_at: datetime | None
    transports: list[str]


class FIDO2CredentialListResponse(BaseModel):
    data: list[FIDO2CredentialView]


__all__ = [
    "FIDO2AssertBeginResponse",
    "FIDO2AssertCompleteInput",
    "FIDO2CredentialListResponse",
    "FIDO2CredentialView",
    "FIDO2RegisterBeginInput",
    "FIDO2RegisterBeginResponse",
    "FIDO2RegisterCompleteInput",
]

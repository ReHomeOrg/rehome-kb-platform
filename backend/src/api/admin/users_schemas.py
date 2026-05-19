"""Pydantic schemas for KbUser CRUD (#230, OpenAPI 04 §KbUser / §KbUserInput).

Email validation — strict format check; full_name — non-empty trimmed.
Permissions — open enum (list of strings, free-form per ТЗ §3.13).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

KbUserRole = Literal["staff_support", "staff_legal", "staff_hr", "staff_admin"]
KbUserStatus = Literal["ACTIVE", "SUSPENDED", "ARCHIVED"]


# Hard cap per OpenAPI: реалистично 5-20 permissions; cap 50 anti-DoS.
_MAX_PERMISSIONS = 50
_MAX_PERMISSION_LENGTH = 64

# Pragmatic email regex — не RFC 5322 (full RFC требует email-validator
# dep, которой нет в requirements.txt). Достаточно для basic format
# check + length bounds. Strict validation — backlog (когда добавим
# `pydantic[email]` extra).
_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _validate_email(value: str) -> str:
    """Lower + format check. Возвращает lowercased для consistency с DB UQ."""
    s = value.strip().lower()
    if not _EMAIL_PATTERN.match(s):
        raise ValueError("Invalid email format")
    if len(s) > 255:
        raise ValueError("Email exceeds 255 chars")
    return s


def _validate_permissions(value: list[str]) -> list[str]:
    """Strip + dedupe + length checks. None permissions → empty list."""
    if value is None:
        return []
    if len(value) > _MAX_PERMISSIONS:
        raise ValueError(f"Too many permissions (max {_MAX_PERMISSIONS})")
    cleaned: list[str] = []
    seen: set[str] = set()
    for p in value:
        stripped = p.strip()
        if not stripped or stripped in seen:
            continue
        if len(stripped) > _MAX_PERMISSION_LENGTH:
            raise ValueError(f"Permission exceeds {_MAX_PERMISSION_LENGTH} chars")
        seen.add(stripped)
        cleaned.append(stripped)
    return cleaned


class KbUserView(BaseModel):
    """OpenAPI §KbUser response schema."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    email: str
    full_name: str
    role: KbUserRole
    permissions: list[str] = Field(default_factory=list)
    status: KbUserStatus
    created_at: datetime
    last_login_at: datetime | None = None
    mfa_enabled: bool = False


class KbUsersPagination(BaseModel):
    """Cursor pagination info."""

    cursor_next: str | None = None
    has_more: bool = False


class KbUsersListResponse(BaseModel):
    """List envelope с cursor pagination."""

    data: list[KbUserView]
    pagination: KbUsersPagination


class KbUserCreate(BaseModel):
    """POST /admin/users body (OpenAPI §KbUserInput)."""

    model_config = ConfigDict(extra="forbid")

    email: str
    full_name: str = Field(min_length=1, max_length=255)
    role: KbUserRole
    permissions: list[str] = Field(default_factory=list)

    @field_validator("email", mode="after")
    @classmethod
    def _v_email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("full_name", mode="after")
    @classmethod
    def _v_full_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("full_name must not be empty/whitespace-only")
        return s

    @field_validator("permissions", mode="after")
    @classmethod
    def _v_permissions(cls, v: list[str]) -> list[str]:
        return _validate_permissions(v)


class KbUserPatch(BaseModel):
    """PATCH /admin/users/{id} body — partial update.

    Email / full_name НЕ patch'аются (security: identity-bound поля
    меняются через отдельный flow с MFA — backlog).

    Permissions — full replacement (НЕ delta) для simplicity.
    """

    model_config = ConfigDict(extra="forbid")

    role: KbUserRole | None = None
    status: KbUserStatus | None = None
    permissions: list[str] | None = None
    # Sync hooks — admin может set'нуть mfa_enabled / last_login_at
    # вручную пока нет KC integration. Backlog: убрать оттуда когда
    # event listener landит.
    mfa_enabled: bool | None = None
    last_login_at: datetime | None = None

    @field_validator("permissions", mode="after")
    @classmethod
    def _v_permissions(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_permissions(v)


__all__ = [
    "KbUserCreate",
    "KbUserPatch",
    "KbUserRole",
    "KbUserStatus",
    "KbUserView",
    "KbUsersListResponse",
    "KbUsersPagination",
]

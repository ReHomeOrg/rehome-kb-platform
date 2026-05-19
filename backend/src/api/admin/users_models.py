"""KbUser ORM model (#230, OpenAPI 04 §KbUser).

Staff user registry — НЕ замена Keycloak. Это metadata layer:
- `email` — unique identity, matches Keycloak preferred_username/email.
- `role` — one of 4 staff roles (см. ADR-0003 scope mapping).
- `permissions` — extra flags поверх role (JSONB open enum).
- `status` lifecycle: ACTIVE → SUSPENDED → ACTIVE (re-activate) или
  → ARCHIVED (soft-delete).

`last_login_at` + `mfa_enabled` — пока ставятся вручную через PATCH;
KC event sync — backlog.

Status / role values mirror'ятся в migration CHECK constraint —
test_check_sync verifies (см. `test_kb_users_check_sync`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base

KB_USER_ROLES: Final[tuple[str, ...]] = (
    "staff_support",
    "staff_legal",
    "staff_hr",
    "staff_admin",
)
KB_USER_STATUSES: Final[tuple[str, ...]] = ("ACTIVE", "SUSPENDED", "ARCHIVED")


class KbUser(Base):
    """KB-staff user record."""

    __tablename__ = "kb_users"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint(
            f"role IN ({', '.join(repr(v) for v in KB_USER_ROLES)})",
            name="ck_kb_users_role",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in KB_USER_STATUSES)})",
            name="ck_kb_users_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<KbUser id={self.id} email={self.email!r} role={self.role}>"


__all__: list[Any] = ["KB_USER_ROLES", "KB_USER_STATUSES", "KbUser"]

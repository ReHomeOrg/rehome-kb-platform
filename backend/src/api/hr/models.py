"""SQLAlchemy ORM model для HrEmployee (#150, #234, PZ §7).

Stage 1: minimal viable employee card — ФИО, должность, hire/termination
dates, status, contact info.

Stage 2 (#234 / ADR-0018): добавлены 4 encrypted ПДн колонки:
- `passport_number_encrypted`, `inn_encrypted`, `snils_encrypted`,
  `bank_account_encrypted` — Fernet-encrypted BYTEA. Plaintext exposed
  только при scope = HR_RESTRICTED (staff_hr / staff_admin) через
  router projection layer.

ADR-0003 access: HR_RESTRICTED tier — только staff_hr / staff_admin /
director видят employee records.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, Index, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class HrEmployee(Base):
    """Карточка сотрудника reHome (PZ §7).

    Status lifecycle: ACTIVE → ON_LEAVE → ACTIVE (round-trip);
    ACTIVE → TERMINATED (terminal, требует termination_date).
    """

    __tablename__ = "hr_employees"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, unique=True)
    personnel_number: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ACTIVE")
    contact_info: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    # ПДн encrypted columns (ADR-0018 Stage 2). Plaintext НЕ хранится;
    # decrypt happens в hr/crypto.py поверх HR_ENCRYPTION_KEY (env).
    # Access — только через scope = HR_RESTRICTED + audit log.
    passport_number_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    inn_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    snils_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    bank_account_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'ON_LEAVE', 'TERMINATED')",
            name="ck_hr_employees_status",
        ),
        CheckConstraint(
            "(status != 'TERMINATED') OR (termination_date IS NOT NULL)",
            name="ck_hr_employees_termination_date_required",
        ),
        Index("ix_hr_employees_status", "status"),
        Index("ix_hr_employees_department", "department"),
        Index("ix_hr_employees_full_name", "full_name"),
    )

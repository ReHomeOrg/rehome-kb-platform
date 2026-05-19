"""Pydantic schemas для kb-hr (#150, PZ §7).

Все endpoints — HR_RESTRICTED tier (только staff_hr / staff_admin /
director). View не отделена от full payload — non-HR scope получает
403 на любые операции с employee records.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EmployeeStatus = Literal["ACTIVE", "ON_LEAVE", "TERMINATED"]


class HrEmployeeView(BaseModel):
    """Полный employee response. Все поля видимы HR_RESTRICTED tier'у.

    ПДн поля (passport_number / inn / snils / bank_account) — decrypted
    plaintext, populated router'ом из BYTEA-колонок через `hr/crypto.py`.
    None = «не заполнено».
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    user_id: UUID | None = None
    personnel_number: str | None = None
    full_name: str
    position: str
    department: str | None = None
    hire_date: date
    termination_date: date | None = None
    status: str
    contact_info: dict[str, Any] = Field(default_factory=dict)
    notes: dict[str, Any] = Field(default_factory=dict)
    # ПДн (ADR-0018) — decrypted на router-layer. None = empty.
    passport_number: str | None = None
    inn: str | None = None
    snils: str | None = None
    bank_account: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class HrEmployeeSummary(BaseModel):
    """Краткая карточка для list endpoint — без notes (потенциально
    содержат sensitive comments)."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    full_name: str
    position: str
    department: str | None = None
    hire_date: date
    status: str
    updated_at: datetime


class HrEmployeeInput(BaseModel):
    """Body для POST /hr/employees.

    ПДн поля (passport_number / inn / snils / bank_account) — plaintext
    на API boundary; repository encrypts перед persisting. Optional,
    «не заполнено» по умолчанию.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    personnel_number: str | None = Field(default=None, max_length=32)
    full_name: str = Field(min_length=1, max_length=200)
    position: str = Field(min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    hire_date: date
    termination_date: date | None = None
    status: EmployeeStatus = "ACTIVE"
    contact_info: dict[str, Any] = Field(default_factory=dict)
    notes: dict[str, Any] = Field(default_factory=dict)
    # ПДн plaintext fields (ADR-0018). Limits — anti-DoS / sanity:
    # passport ≤ 64 char, inn 12 digits, snils 14 chars, bank ≤ 32.
    passport_number: str | None = Field(default=None, max_length=64)
    inn: str | None = Field(default=None, max_length=32)
    snils: str | None = Field(default=None, max_length=32)
    bank_account: str | None = Field(default=None, max_length=64)


class HrEmployeePatch(BaseModel):
    """Body для PATCH /hr/employees/{id} — partial update.

    ПДн поля могут patch'аться: значение → re-encrypt; пустая строка
    `""` нормализуется в clearing (encrypted column → NULL).
    """

    model_config = ConfigDict(extra="forbid")

    personnel_number: str | None = Field(default=None, max_length=32)
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    position: str | None = Field(default=None, min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    hire_date: date | None = None
    termination_date: date | None = None
    status: EmployeeStatus | None = None
    contact_info: dict[str, Any] | None = None
    notes: dict[str, Any] | None = None
    passport_number: str | None = Field(default=None, max_length=64)
    inn: str | None = Field(default=None, max_length=32)
    snils: str | None = Field(default=None, max_length=32)
    bank_account: str | None = Field(default=None, max_length=64)


class PaginationInfo(BaseModel):
    cursor_next: str | None = None
    has_more: bool = False


class HrEmployeeListResponse(BaseModel):
    data: list[HrEmployeeSummary]
    pagination: PaginationInfo

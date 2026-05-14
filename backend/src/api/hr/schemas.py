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
    """Полный employee response. Все поля видимы HR_RESTRICTED tier'у."""

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
    """Body для POST /hr/employees."""

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


class HrEmployeePatch(BaseModel):
    """Body для PATCH /hr/employees/{id} — partial update."""

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


class PaginationInfo(BaseModel):
    cursor_next: str | None = None
    has_more: bool = False


class HrEmployeeListResponse(BaseModel):
    data: list[HrEmployeeSummary]
    pagination: PaginationInfo

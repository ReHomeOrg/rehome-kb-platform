"""Pydantic schemas для PersonalDataRequest (#232, OpenAPI §PersonalDataRequest)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

PdRequestType = Literal["provide", "correct", "delete", "transfer"]
PdRequestStatus = Literal["NEW", "IN_PROGRESS", "COMPLETED", "REJECTED", "OVERDUE"]

# PATCH-only statuses (manual): NEW only через ingest path (отсутствует
# в OpenAPI); OVERDUE — auto-set worker'ом.
PdRequestPatchStatus = Literal["IN_PROGRESS", "COMPLETED", "REJECTED"]


class PersonalDataRequestView(BaseModel):
    """OpenAPI §PersonalDataRequest."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    type: PdRequestType
    status: PdRequestStatus
    subject_id: UUID
    subject_email: str | None = None
    subject_phone: str | None = None
    description: str | None = None
    assigned_to: UUID | None = None
    created_at: datetime
    due_at: datetime
    completed_at: datetime | None = None
    resolution_note: str | None = None
    attachments: list[UUID] = Field(default_factory=list)


class PersonalDataRequestPagination(BaseModel):
    cursor_next: str | None = None
    has_more: bool = False


class PersonalDataRequestsListResponse(BaseModel):
    data: list[PersonalDataRequestView]
    pagination: PersonalDataRequestPagination


class PersonalDataRequestPatch(BaseModel):
    """PATCH per OpenAPI §processPersonalDataRequest.

    Updatable: status (required-by-OpenAPI), resolution_note, attachments.
    Identity / subject поля (type / subject_id / etc.) — НЕ patch'аются.
    """

    model_config = ConfigDict(extra="forbid")

    # OpenAPI: required. Status переходы валидируются repository state machine.
    status: PdRequestPatchStatus
    resolution_note: str | None = Field(default=None, max_length=4000)
    attachments: list[UUID] | None = None

    @field_validator("attachments", mode="after")
    @classmethod
    def _v_attachments(cls, v: list[UUID] | None) -> list[UUID] | None:
        if v is None:
            return None
        # Dedup preserving order.
        seen: set[UUID] = set()
        out: list[UUID] = []
        for u in v:
            if u not in seen:
                seen.add(u)
                out.append(u)
        # Anti-DoS cap.
        if len(out) > 50:
            raise ValueError("Too many attachments (max 50)")
        return out


__all__ = [
    "PdRequestPatchStatus",
    "PdRequestStatus",
    "PdRequestType",
    "PersonalDataRequestPagination",
    "PersonalDataRequestPatch",
    "PersonalDataRequestView",
    "PersonalDataRequestsListResponse",
]

"""Pydantic schemas для audit search endpoint (#163)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditRecordView(BaseModel):
    """Single audit_log row для compliance UI."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    actor_sub: str
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="audit_metadata")
    created_at: datetime


class AuditListResponse(BaseModel):
    data: list[AuditRecordView]
    pagination: dict[str, int]

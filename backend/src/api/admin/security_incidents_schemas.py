"""Pydantic schemas для SecurityIncident (#231, OpenAPI §SecurityIncident)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

IncidentSeverity = Literal["low", "medium", "high", "critical"]
IncidentStatus = Literal["OPEN", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"]
IncidentDetectedBy = Literal["monitoring", "audit", "user_report", "staff", "automated_scan"]


class SecurityIncidentView(BaseModel):
    """OpenAPI §SecurityIncident response."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    incident_type: str
    severity: IncidentSeverity
    status: IncidentStatus
    detected_at: datetime
    detected_by: IncidentDetectedBy
    affected_resources: list[dict[str, Any]] = Field(default_factory=list)
    rkn_notification_required: bool = False
    rkn_notified_at: datetime | None = None
    resolution_note: str | None = None
    resolved_at: datetime | None = None


class SecurityIncidentPagination(BaseModel):
    cursor_next: str | None = None
    has_more: bool = False


class SecurityIncidentsListResponse(BaseModel):
    data: list[SecurityIncidentView]
    pagination: SecurityIncidentPagination


class SecurityIncidentPatch(BaseModel):
    """PATCH body per OpenAPI §updateSecurityIncident.

    Updatable: status / resolution_note / rkn_notified_at.
    Identity-bound поля (incident_type / severity / detected_at /
    detected_by / affected_resources) — НЕ patch'аются (they describe
    the event as detected).
    """

    model_config = ConfigDict(extra="forbid")

    status: IncidentStatus | None = None
    resolution_note: str | None = Field(default=None, max_length=2000)
    rkn_notified_at: datetime | None = None


__all__ = [
    "IncidentDetectedBy",
    "IncidentSeverity",
    "IncidentStatus",
    "SecurityIncidentPagination",
    "SecurityIncidentPatch",
    "SecurityIncidentView",
    "SecurityIncidentsListResponse",
]

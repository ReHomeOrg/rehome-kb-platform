"""Pydantic schemas для `/api/v1/admin/audit-log` (#237).

Projection из `AuditLog` ORM модели в OpenAPI §AuditLogEntry shape.
Missing fields (`actor_type`, `actor_role`, `ip`, `user_agent`,
`request_id`, `severity`) — null defaults (см. audit_log_router
docstring).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.api.audit.models import AuditLog

AdminAuditLogSeverity = Literal["info", "warning", "error", "critical"]


class AuditLogEntryView(BaseModel):
    """OpenAPI 04 §AuditLogEntry projection.

    `actor_id` хранится как string (permissive): backend имеет случаи
    actor_sub=`"staff"` (system actor) — это не UUID, но spec'у соответствует
    `[string, 'null']`-style. Мы намеренно ослабляем UUID format для
    совместимости со существующими данными.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    ts: datetime
    actor_id: str
    actor_type: str | None = None
    actor_role: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    # Honest stub: severity column отсутствует в audit_log (миграция #102).
    # Default `"info"` — единственное sensible значение пока column не
    # будет добавлен. Filter принимаем но не применяем (см. router).
    severity: AdminAuditLogSeverity = "info"
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_model(cls, row: AuditLog) -> AuditLogEntryView:
        return cls(
            id=str(row.id),
            ts=row.created_at,
            actor_id=row.actor_sub,
            action=row.action,
            entity_type=row.resource_type,
            entity_id=row.resource_id,
            details=row.audit_metadata or {},
        )


class AdminAuditLogPagination(BaseModel):
    """OpenAPI 04 §Pagination для cursor-paginated результата."""

    model_config = ConfigDict(extra="forbid")

    cursor_next: str | None = None
    cursor_prev: str | None = None
    has_more: bool = False
    total_estimate: int = 0


class AdminAuditLogListResponse(BaseModel):
    """Envelope для GET /admin/audit-log."""

    model_config = ConfigDict(extra="forbid")

    data: list[AuditLogEntryView]
    pagination: AdminAuditLogPagination


__all__ = [
    "AdminAuditLogListResponse",
    "AdminAuditLogPagination",
    "AdminAuditLogSeverity",
    "AuditLogEntryView",
]

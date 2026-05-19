"""Schemas для /admin/tasks/{id}, /admin/reindex, /admin/cache (#238).

OpenAPI 04 §getTaskStatus — universal task envelope.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.api.admin.tasks_models import AdminTask

TaskStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
TaskType = Literal["reindex", "audit_log_export", "cache_invalidation", "eval_run"]
ReindexScope = Literal["all", "articles", "documents", "premises_cards"]
CacheScope = Literal["all", "articles", "documents", "premises_cards", "search"]


class TaskStatusView(BaseModel):
    """OpenAPI 04 §getTaskStatus response data."""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    type: TaskType
    status: TaskStatus
    progress_percent: int = Field(ge=0, le=100, default=0)
    created_at: datetime
    completed_at: datetime | None = None
    result_url: str | None = None
    error: str | None = None

    @classmethod
    def from_model(cls, row: AdminTask) -> TaskStatusView:
        return cls(
            task_id=row.id,
            type=row.type,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            progress_percent=row.progress_percent,
            created_at=row.created_at,
            completed_at=row.completed_at,
            result_url=row.result_url,
            error=row.error,
        )


class ReindexRequest(BaseModel):
    """POST /admin/reindex body."""

    model_config = ConfigDict(extra="forbid")

    scope: ReindexScope = "all"


class ReindexResponse(BaseModel):
    """POST /admin/reindex response (per OpenAPI 04)."""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID


ExportFormat = Literal["csv", "json"]


class AuditLogExportRequest(BaseModel):
    """POST /admin/audit-log/export body (per OpenAPI 04 §exportAuditLog).

    `filters` — opaque dict матчит формат `/audit-log` filter params:
    `{"actor_sub": ..., "resource_type": ..., "action": ..., "q": ...}`.
    Unknown ключи отбрасываются builder'ом result_url.
    """

    model_config = ConfigDict(extra="forbid")

    from_: datetime = Field(alias="from")
    to: datetime
    filters: dict[str, str] = Field(default_factory=dict)
    format: ExportFormat = "csv"
    reason: str | None = Field(default=None, max_length=500)


class AuditLogExportResponse(BaseModel):
    """POST /admin/audit-log/export response (per OpenAPI 04 §exportAuditLog)."""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    # `estimated_ready_at` (per OpenAPI) — null т.к. execution sync;
    # task сразу в COMPLETED status. Для async migration это поле будет
    # carries SLA estimate.
    estimated_ready_at: datetime | None = None


__all__ = [
    "AuditLogExportRequest",
    "AuditLogExportResponse",
    "CacheScope",
    "ExportFormat",
    "ReindexRequest",
    "ReindexResponse",
    "ReindexScope",
    "TaskStatus",
    "TaskStatusView",
    "TaskType",
]

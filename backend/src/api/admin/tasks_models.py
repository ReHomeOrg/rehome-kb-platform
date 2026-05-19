"""AdminTask ORM model (#238, OpenAPI 04 §getTaskStatus).

Универсальный task registry для async admin операций (reindex,
audit-log export, eval-runs, в будущем — cache invalidation если
heavy). Возвращает task_id и status через GET /admin/tasks/{id}.

MVP execution model: sync execution в самом router'е (нет Dramatiq /
external worker integration). Task row создаётся, status=COMPLETED
ставится сразу после выполнения. Это даёт consistent task_id surface
для admin UI; switch на real async runner — backlog (отдельный эпик
по worker infrastructure).

Type enum (`type`):
- `reindex` — POST /admin/reindex
- `audit_log_export` — POST /admin/audit-log/export
- `cache_invalidation` — DELETE /admin/cache (создаётся только если
  cache layer запущен; в MVP — direct 202 без task row).
- `eval_run` — POST /admin/llm/eval-runs (backlog)

Status lifecycle (per OpenAPI):
  PENDING → RUNNING → COMPLETED | FAILED | CANCELLED

Retention: 30 дней. Cleanup worker — backlog. На MVP таблица растёт.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base

TASK_TYPES: Final[tuple[str, ...]] = (
    "reindex",
    "audit_log_export",
    "cache_invalidation",
    "eval_run",
)
TASK_STATUSES: Final[tuple[str, ...]] = (
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
TERMINAL_TASK_STATUSES: Final[frozenset[str]] = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class AdminTask(Base):
    """Universal async task registry для admin endpoints."""

    __tablename__ = "admin_tasks"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # `params` — input args task'а (для debug / replay). Например для
    # reindex: `{"scope": "articles"}`; для audit-log export: from/to/filters.
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # `result_url` (per OpenAPI) — URL готового артефакта (CSV для export,
    # null для reindex/cache).
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # actor_sub — кто запустил task (audit trail).
    actor_sub: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"type IN ({', '.join(repr(v) for v in TASK_TYPES)})",
            name="ck_admin_tasks_type",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in TASK_STATUSES)})",
            name="ck_admin_tasks_status",
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100",
            name="ck_admin_tasks_progress_range",
        ),
        # Terminal status ↔ completed_at set.
        CheckConstraint(
            "(completed_at IS NULL AND status IN ('PENDING', 'RUNNING')) "
            "OR (completed_at IS NOT NULL AND status IN "
            "('COMPLETED', 'FAILED', 'CANCELLED'))",
            name="ck_admin_tasks_completed_at_consistency",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AdminTask id={self.id} type={self.type} status={self.status}>"


__all__ = [
    "TASK_STATUSES",
    "TASK_TYPES",
    "TERMINAL_TASK_STATUSES",
    "AdminTask",
]

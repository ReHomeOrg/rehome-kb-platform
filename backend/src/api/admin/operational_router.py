"""Operational admin endpoints (#238): cache, reindex, tasks/{id}.

OpenAPI 04:
- `DELETE /api/v1/admin/cache` (invalidateCache) — invalidates kb-search /
  retrieval caches. MVP — honest stub: backend не имеет explicit cache
  layer (per state-of-code). Endpoint возвращает 202 + audit-log запись;
  noop'нется на текущей архитектуре.
- `POST /api/v1/admin/reindex` (reindexContent) — пересоздаёт article
  embeddings index. Wires to `IndexerService.reindex_all` (фоновый
  пересчёт всех articles).
- `GET /api/v1/admin/tasks/{task_id}` (getTaskStatus) — universal task
  status lookup.

Execution model (ADR-0020 B): handler создаёт PENDING task row +
spawn'ит background coroutine через `AdminTaskRunner` (asyncio task +
`task_reaper` для crash recovery). Handler возвращает 202 + task_id
сразу — client poll'ит `/admin/tasks/{id}` для status updates.

RBAC: staff_admin (STAFF + LEGAL). Cache invalidation и reindex —
operational операции с высокой стоимостью; не должны быть доступны
staff_support / staff_hr.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.task_runner import AdminTaskRunner, get_admin_task_runner
from src.api.admin.tasks_repository import (
    AdminTaskRepository,
    get_admin_task_repository,
)
from src.api.admin.tasks_schemas import (
    CacheScope,
    ReindexRequest,
    ReindexResponse,
    TaskStatusView,
)
from src.api.audit.actions import (
    ACTION_ADMIN_CACHE_INVALIDATED,
    ACTION_ADMIN_REINDEX_TRIGGERED,
    RESOURCE_ADMIN_CACHE,
    RESOURCE_ADMIN_TASK,
)
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.db import get_session

router = APIRouter(prefix="/admin", tags=["Admin"])


def _require_staff_admin(access_levels: frozenset[AccessLevel]) -> None:
    """staff_admin scope (STAFF + LEGAL)."""
    if not (AccessLevel.STAFF in access_levels and AccessLevel.LEGAL in access_levels):
        raise HTTPException(
            status_code=403,
            detail="Требуется staff_admin scope",
        )


@router.delete(
    "/cache",
    status_code=202,
    summary="Инвалидация кеша (staff_admin)",
    responses={
        202: {"description": "Инвалидация запущена"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
    },
)
async def invalidate_cache(
    scope: CacheScope = Query(default="all"),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> dict[str, str]:
    """`DELETE /api/v1/admin/cache` (OpenAPI 04 §invalidateCache).

    Honest stub: backend не имеет explicit cache layer (нет Redis cache,
    нет in-memory caching beyond per-request session). Endpoint
    возвращает 202 + audit_log запись для compliance trail.

    Когда cache layer landит — изменится только реализация (audit row
    остаётся как trigger record для invalidation worker'а).
    """
    _require_staff_admin(access_levels)

    actor_sub = claims.get("sub", "unknown")
    await audit_repo.record(
        actor_sub=actor_sub,
        action=ACTION_ADMIN_CACHE_INVALIDATED,
        resource_type=RESOURCE_ADMIN_CACHE,
        resource_id=scope,
        metadata={"scope": scope},
    )
    return {"status": "accepted", "scope": scope}


@router.post(
    "/reindex",
    response_model=ReindexResponse,
    status_code=202,
    summary="Принудительная переиндексация (staff_admin)",
    responses={
        202: {"description": "Запущено"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
    },
)
async def reindex_content(
    body: ReindexRequest | None = None,
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: AdminTaskRepository = Depends(get_admin_task_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    runner: AdminTaskRunner = Depends(get_admin_task_runner),
    session: AsyncSession = Depends(get_session),
) -> ReindexResponse:
    """`POST /api/v1/admin/reindex` (OpenAPI 04 §reindexContent, #268 async).

    Per ADR-0020 Вариант B (asyncio.create_task pattern):
    1. Create admin_tasks row (status=PENDING).
    2. Audit запись `admin.reindex.triggered`.
    3. Spawn background coroutine через `runner.spawn_reindex(...)`.
    4. Return 202 + task_id immediately (request не блокируется).

    Background task (см. `task_runner._run_reindex`):
    - Opens own DB session.
    - mark_running → execute IndexerService.reindex_all_articles →
      mark_completed (или mark_failed if errors_total > 0 with 0 processed).
    - Crash recovery: reaper (см. `task_reaper`) cleans stale RUNNING
      rows на app restart (>15min).

    Scope behavior:
    - `articles` / `all` — реальный reindex.
    - `documents` / `premises_cards` — honest stub (task COMPLETED без work).
    """
    _require_staff_admin(access_levels)
    payload = body or ReindexRequest()
    actor_sub = str(claims.get("sub", "unknown"))

    task = await repo.create(
        type_="reindex",
        actor_sub=actor_sub,
        params={"scope": payload.scope},
    )
    await audit_repo.record(
        actor_sub=actor_sub,
        action=ACTION_ADMIN_REINDEX_TRIGGERED,
        resource_type=RESOURCE_ADMIN_TASK,
        resource_id=str(task.id),
        metadata={"scope": payload.scope},
    )

    # CRITICAL: commit BEFORE spawn. Background task opens own session;
    # без commit'а task row невидим для него → LookupError. Race
    # документирован в state-of-code CS.12 (2026-05-27 known bug fix).
    await session.commit()

    # Spawn background coroutine (asyncio.create_task). Request returns
    # 202 immediately; background task transitions PENDING → RUNNING →
    # COMPLETED/FAILED via own session.
    runner.spawn_reindex(task.id, payload.scope, actor_sub)
    return ReindexResponse(task_id=task.id)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusView,
    summary="Статус фоновой задачи (staff_admin)",
    responses={
        200: {"description": "OK"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Task не найден"},
    },
)
async def get_task_status(
    task_id: UUID,
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: AdminTaskRepository = Depends(get_admin_task_repository),
) -> TaskStatusView:
    """`GET /api/v1/admin/tasks/{task_id}` (OpenAPI 04 §getTaskStatus).

    Universal task status lookup. Используется admin UI для polling'а
    долгих операций (reindex, audit-log export — будущее).
    """
    _require_staff_admin(access_levels)
    row = await repo.get(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} не найден")
    return TaskStatusView.from_model(row)


__all__ = ["router"]

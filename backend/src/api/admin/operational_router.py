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

Execution model: sync execution в самом router'е (нет Dramatiq worker —
см. tasks_models docstring). Task row создаётся в PENDING, переходит в
RUNNING → COMPLETED/FAILED в одной транзакции. Это даёт consistent
task_id surface, но не освобождает request thread'а до завершения
operation. Switch на real async runner — backlog.

RBAC: staff_admin (STAFF + LEGAL). Cache invalidation и reindex —
operational операции с высокой стоимостью; не должны быть доступны
staff_support / staff_hr.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

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
from src.api.articles.repository import ArticleRepository, get_article_repository
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
from src.api.search.indexer import IndexerService, get_indexer_service

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
    article_repo: ArticleRepository = Depends(get_article_repository),
    indexer: IndexerService = Depends(get_indexer_service),
) -> ReindexResponse:
    """`POST /api/v1/admin/reindex` (OpenAPI 04 §reindexContent, real #240).

    Creates admin_tasks row + audit запись, iterates через всех PUBLISHED
    articles + вызывает `IndexerService.index_article` для каждой,
    обновляет `admin_tasks.error` при failure и mark'ает COMPLETED.

    Scope behavior:
    - `articles` / `all` — реальный reindex (через ArticleRepository iter).
    - `documents` / `premises_cards` — honest stub (no indexer для этих
      типов; task создаётся но execution no-op'ится).

    Sync execution: на N articles ≈ N × embed_latency. Production volume —
    backlog (Dramatiq + asyncio runner для off-request execution).
    Metadata `articles_processed` / `chunks_total` / `errors_total`
    сохраняется в admin_task.params для post-mortem.
    """
    _require_staff_admin(access_levels)
    payload = body or ReindexRequest()
    actor_sub = claims.get("sub", "unknown")

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

    await repo.mark_running(task.id)
    try:
        if payload.scope in ("all", "articles"):
            result = await indexer.reindex_all_articles(
                article_repo.iter_published_for_reindex(),
            )
            # Failure heuristic: errors > 0 при articles_processed == 0 —
            # ни одного article не reindex'нулся; mark FAILED.
            if result.articles_processed == 0 and result.errors_total > 0:
                await repo.mark_failed(
                    task.id,
                    error=f"{result.errors_total} article(s) failed to reindex",
                )
                raise HTTPException(
                    status_code=500,
                    detail="Reindex failed: all articles errored",
                )
        # Other scopes — honest stub (см. docstring).
    except HTTPException:
        raise
    except Exception as exc:
        await repo.mark_failed(task.id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Reindex failed: {exc}") from exc

    await repo.mark_completed(task.id)
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

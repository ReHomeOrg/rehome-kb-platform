"""/admin/llm/eval-runs router (#244, OpenAPI 04 §startEvalRun / §listEvalRuns).

POST — запустить eval run (sync execution, results inline в admin_tasks).
GET — list recent runs projected per OpenAPI EvalRun shape.

RBAC: staff_admin (STAFF + LEGAL). Eval-стенд показывает aggregate
metrics + cost — staff_support / staff_hr scope не нужен.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.admin.eval_runs_schemas import (
    EvalRunListResponse,
    EvalRunStartRequest,
    EvalRunStartResponse,
)
from src.api.admin.eval_runs_service import (
    EvalRunsService,
    EvalRunValidationError,
)
from src.api.admin.tasks_repository import (
    AdminTaskRepository,
    get_admin_task_repository,
)
from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel

router = APIRouter(prefix="/admin/llm", tags=["Admin"])

# `listEvalRuns` cap — anti-DoS на large admin_tasks tables.
_LIST_LIMIT_DEFAULT = 50
_LIST_LIMIT_MAX = 200


def _require_staff_admin(access_levels: frozenset[AccessLevel]) -> None:
    if not (AccessLevel.STAFF in access_levels and AccessLevel.LEGAL in access_levels):
        raise HTTPException(
            status_code=403,
            detail="Требуется staff_admin scope",
        )


def _get_eval_runs_service(
    repo: AdminTaskRepository = Depends(get_admin_task_repository),
) -> EvalRunsService:
    return EvalRunsService(repo)


@router.post(
    "/eval-runs",
    response_model=EvalRunStartResponse,
    status_code=202,
    summary="Запустить новый прогон eval (staff_admin)",
    responses={
        202: {"description": "Запущено"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        422: {"description": "Невалидный provider / test_set"},
    },
)
async def start_eval_run(
    request: EvalRunStartRequest,
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    service: EvalRunsService = Depends(_get_eval_runs_service),
) -> EvalRunStartResponse:
    """`POST /api/v1/admin/llm/eval-runs` (OpenAPI 04 §startEvalRun).

    MVP: `mock` provider + `smoke` test_set (10 pairs from golden.jsonl).
    Real providers / full dataset / custom_questions — backlog (см.
    ADR-0013 + eval_runs_service docstring).

    Sync execution — running task сразу marks COMPLETED после
    aggregation. Switch на real async worker — backlog.
    """
    _require_staff_admin(access_levels)
    actor_sub = claims.get("sub", "unknown")
    try:
        task = await service.start_run(request, actor_sub=actor_sub)
    except EvalRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EvalRunStartResponse(run_id=task.id)


@router.get(
    "/eval-runs",
    response_model=EvalRunListResponse,
    summary="История прогонов eval-стенда (staff_admin)",
    responses={
        200: {"description": "OK"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
    },
)
async def list_eval_runs(
    provider: str | None = Query(default=None, max_length=64),
    cursor: str | None = Query(default=None, max_length=200),  # noqa: ARG001 — backlog
    limit: int = Query(default=_LIST_LIMIT_DEFAULT, ge=1, le=_LIST_LIMIT_MAX),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: AdminTaskRepository = Depends(get_admin_task_repository),
) -> EvalRunListResponse:
    """`GET /api/v1/admin/llm/eval-runs` (OpenAPI 04 §listEvalRuns).

    Lists eval_run admin_tasks DESC по created_at. Optional `?provider=X`
    filters runs где X в params.providers list.

    Cursor pagination — backlog (admin UI MVP полностью fits в limit=200).
    """
    _require_staff_admin(access_levels)
    rows = await repo.list_recent(type_="eval_run", limit=limit)

    summaries = [EvalRunsService.project_to_summary(r) for r in rows]
    if provider is not None:
        summaries = [s for s in summaries if provider in s.providers]
    return EvalRunListResponse(data=summaries)


__all__ = ["router"]

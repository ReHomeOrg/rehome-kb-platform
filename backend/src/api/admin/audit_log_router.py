"""`/api/v1/admin/audit-log` (#237, OpenAPI 04 §getAuditLog).

Adapter поверх `AuditRepository.list_records_keyset` — адаптирует OpenAPI
04 параметризацию (`actor_id` / `entity_type` / `entity_id` / `from` /
`to` / `cursor`) к внутренней модели audit_log (`actor_sub` /
`resource_type` / `resource_id` / since/until / `(created_at, id)`
keyset cursor).

Существующий публичный `/api/v1/audit-log` остаётся (LEGAL access),
этот alias — admin UI surface с staff_admin gate per OpenAPI.

Mapping notes:
- `actor_id` → `actor_sub`. В нашей модели `actor_sub` — string (typically
  Keycloak UUID, иногда `"staff"`-like для service-actor); spec требует
  UUID format, но мы делаем permissive (string projection в response).
- `entity_type` / `entity_id` → `resource_type` / `resource_id`.
- `severity` — OpenAPI поле, в БД отсутствует. Filter принимаем но
  игнорируем (honest stub: фильтр no-op'нется). Response severity =
  `"info"` default (consistent placeholder).
- `actor_type` / `actor_role` / `ip` / `user_agent` / `request_id` —
  нет в `audit_log` (миграция #102 — minimal schema). Сериализуются
  null'ами. Полный набор полей — backlog (требует ALTER TABLE +
  middleware capture point).
- Cursor pagination: opaque keyset `(created_at, id)` через общий
  `articles/cursor.py::encode_cursor` / `decode_cursor`. `cursor_prev`
  null'ится — keyset back-navigation требует отдельного reversed query,
  admin UI обходится browser history. `total_estimate` — len(visible) +
  (1 if has_more); точный COUNT(*) overkill для compliance review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.audit_log_schemas import (
    AdminAuditLogListResponse,
    AdminAuditLogPagination,
    AdminAuditLogSeverity,
    AuditLogEntryView,
)
from src.api.admin.task_runner import AdminTaskRunner, get_admin_task_runner
from src.api.admin.tasks_repository import (
    AdminTaskRepository,
    get_admin_task_repository,
)
from src.api.admin.tasks_schemas import (
    AuditLogExportRequest,
    AuditLogExportResponse,
)
from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.audit.actions import (
    ACTION_ADMIN_AUDIT_LOG_EXPORTED,
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

# Allowed filter keys для /audit-log/export.csv URL builder'а.
# Любые другие keys в `filters` body отбрасываются (anti-injection в URL).
_ALLOWED_EXPORT_FILTER_KEYS: frozenset[str] = frozenset(
    {"actor_sub", "resource_type", "resource_id", "action", "q"}
)

# Hard cap per OpenAPI spec (`limit: maximum: 500`).
_MAX_LIMIT = 500
_DEFAULT_LIMIT = 50


def _require_staff_admin_or_legal(access_levels: frozenset[AccessLevel]) -> None:
    """staff_admin или staff_legal scope per OpenAPI.

    Реальный gate — `AccessLevel.LEGAL` (admin/legal оба имеют LEGAL).
    Существующий /audit-log использует тот же LEGAL gate — мы намеренно
    воспроизводим политику (admin/audit-log — alias surface, не более
    строгая ACL).
    """
    if AccessLevel.LEGAL not in access_levels:
        raise HTTPException(
            status_code=403,
            detail="Требуется staff_admin или staff_legal scope",
        )


@router.get(
    "/audit-log",
    response_model=AdminAuditLogListResponse,
    response_model_by_alias=True,
    summary="Аудит-лог системы (staff_admin / staff_legal)",
    responses={
        400: {"description": "Невалидный cursor"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin или staff_legal scope"},
        422: {"description": "Невалидный параметр"},
    },
)
async def get_admin_audit_log(
    actor_id: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=64),
    entity_type: str | None = Query(default=None, max_length=32),
    entity_id: str | None = Query(default=None, max_length=200),
    severity: AdminAuditLogSeverity | None = Query(default=None),  # noqa: ARG001 — honest stub
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: AuditRepository = Depends(get_audit_repository),
) -> AdminAuditLogListResponse:
    """`GET /api/v1/admin/audit-log` (OpenAPI 04 §getAuditLog).

    Same data что и `/audit-log`, но с OpenAPI-compliant param names и
    keyset cursor pagination (`(created_at, id)` DESC). Существующий
    `/audit-log` остаётся для backward compat (offset pagination, used
    LEGAL middleware напрямую).

    `severity` filter — accepted но не применяется (no column; honest
    stub до landing'а severity field миграции). Response `severity`
    field = `"info"` default.
    """
    _require_staff_admin_or_legal(access_levels)

    decoded = decode_cursor(cursor) if cursor else None

    rows, has_more = await repo.list_records_keyset(
        actor_sub=actor_id,
        resource_type=entity_type,
        resource_id=entity_id,
        action=action,
        since=from_,
        until=to,
        q=None,
        cursor=decoded,
        limit=limit,
    )

    cursor_next: str | None = None
    if rows and has_more:
        last = rows[-1]
        cursor_next = encode_cursor(last.created_at, last.id)

    entries = [AuditLogEntryView.from_model(r) for r in rows]

    return AdminAuditLogListResponse(
        data=entries,
        pagination=AdminAuditLogPagination(
            cursor_next=cursor_next,
            # Keyset не поддерживает cheap backward navigation — нужен
            # отдельный reversed-keyset query. Admin UI обходится browser
            # history; field оставлен в schema для OpenAPI compat (всегда
            # null с keyset).
            cursor_prev=None,
            has_more=has_more,
            # `total_estimate` per OpenAPI «Приблизительная оценка».
            # Keyset не знает absolute offset; даём lower-bound оценку
            # «есть как минимум столько rows на этой странице (+1 если
            # is_more)». Точный count требует COUNT(*) и overkill для
            # admin compliance review.
            total_estimate=len(rows) + (1 if has_more else 0),
        ),
    )


# ---------------------------------------------------------------------------
# POST /admin/audit-log/export (#239, OpenAPI 04 §exportAuditLog)


def _build_export_url(payload: AuditLogExportRequest) -> str:
    """Build result_url poking at /audit-log/export.{csv,jsonl}.

    Reuses real LEGAL-gated export endpoint (frontend fetches result_url
    с тем же auth). Альтернатива (хранить blob в admin_tasks) — out of
    scope: текущий sync-execution model + дешевая регенерация дампа на
    запрос — proportional к compliance use case.

    Format dispatch (#352):
    - `csv` → /audit-log/export.csv (default, Excel-friendly).
    - `json` → /audit-log/export.jsonl (newline-delimited, parseable
      line-by-line; `Content-Type: application/x-ndjson`).
    """
    params: dict[str, str] = {
        "since": payload.from_.isoformat(),
        "until": payload.to.isoformat(),
    }
    # Whitelist filter keys (см. _ALLOWED_EXPORT_FILTER_KEYS).
    for key, value in payload.filters.items():
        if key in _ALLOWED_EXPORT_FILTER_KEYS and value:
            params[key] = value
    extension = "jsonl" if payload.format == "json" else "csv"
    return f"/api/v1/audit-log/export.{extension}?{urlencode(params)}"


@router.post(
    "/audit-log/export",
    response_model=AuditLogExportResponse,
    status_code=202,
    summary="Экспорт аудит-лога (staff_admin / staff_legal)",
    responses={
        202: {"description": "Принято, задача создана"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin или staff_legal scope"},
        422: {"description": "Невалидные параметры"},
    },
)
async def export_admin_audit_log(
    payload: AuditLogExportRequest,
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    task_repo: AdminTaskRepository = Depends(get_admin_task_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    runner: AdminTaskRunner = Depends(get_admin_task_runner),
    session: AsyncSession = Depends(get_session),
) -> AuditLogExportResponse:
    """`POST /api/v1/admin/audit-log/export` (OpenAPI 04 §exportAuditLog).

    Per ADR-0020 Вариант B (#268 async pattern):
    1. Create admin_tasks row (status=PENDING) + audit запись.
    2. Spawn background coroutine — marks COMPLETED с result_url
       указывающим на существующий /api/v1/audit-log/export.csv.
    3. Return 202 + task_id immediately.

    `reason` сохраняется в task.params + audit metadata (compliance).
    `filters` whitelist'ятся через `_ALLOWED_EXPORT_FILTER_KEYS` —
    unknown keys отбрасываются (anti-injection в URL).
    """
    _require_staff_admin_or_legal(access_levels)
    actor_sub = str(claims.get("sub", "unknown"))

    task = await task_repo.create(
        type_="audit_log_export",
        actor_sub=actor_sub,
        params={
            "from": payload.from_.isoformat(),
            "to": payload.to.isoformat(),
            "filters": payload.filters,
            "format": payload.format,
            "reason": payload.reason,
        },
    )
    await audit_repo.record(
        actor_sub=actor_sub,
        action=ACTION_ADMIN_AUDIT_LOG_EXPORTED,
        resource_type=RESOURCE_ADMIN_TASK,
        resource_id=str(task.id),
        metadata={
            "format": payload.format,
            "reason": payload.reason,
        },
    )

    result_url = _build_export_url(payload)
    # Commit BEFORE spawn — background coroutine opens own session
    # и upper'ит task.id; без commit'а row невидим (тот же race fix
    # как в operational_router.reindex_content).
    await session.commit()
    runner.spawn_audit_export(task.id, result_url, actor_sub)

    return AuditLogExportResponse(task_id=task.id, estimated_ready_at=None)


__all__ = ["router"]

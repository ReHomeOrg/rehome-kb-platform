"""`/api/v1/admin/audit-log` (#237, OpenAPI 04 §getAuditLog).

Adapter поверх существующего `AuditRepository.list_records` —
адаптирует OpenAPI 04 параметризацию (`actor_id` / `entity_type` /
`entity_id` / `from` / `to` / `cursor`) к внутренней модели audit_log
(`actor_sub` / `resource_type` / `resource_id` / since/until / offset).

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
- Cursor pagination: opaque base64-encoded offset (simple для MVP;
  proper keyset на `(created_at, id)` — backlog после миграции
  index'а).
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.admin.audit_log_schemas import (
    AdminAuditLogListResponse,
    AdminAuditLogPagination,
    AdminAuditLogSeverity,
    AuditLogEntryView,
)
from src.api.admin.tasks_repository import (
    AdminTaskRepository,
    get_admin_task_repository,
)
from src.api.admin.tasks_schemas import (
    AuditLogExportRequest,
    AuditLogExportResponse,
)
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

router = APIRouter(prefix="/admin", tags=["Admin"])

# Allowed filter keys для /audit-log/export.csv URL builder'а.
# Любые другие keys в `filters` body отбрасываются (anti-injection в URL).
_ALLOWED_EXPORT_FILTER_KEYS: frozenset[str] = frozenset(
    {"actor_sub", "resource_type", "resource_id", "action", "q"}
)

# Hard cap per OpenAPI spec (`limit: maximum: 500`).
_MAX_LIMIT = 500
_DEFAULT_LIMIT = 50


def _decode_cursor(cursor: str | None) -> int:
    """Cursor → offset. Empty/None → 0. Invalid → 422.

    Простой opaque base64-encoded integer offset. Switch на keyset
    cursor `(created_at DESC, id DESC)` — backlog (нужен composite
    index + repo support).
    """
    if not cursor:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        value = int(decoded)
        if value < 0:
            raise ValueError("negative offset")
        return value
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid cursor: {exc}") from exc


def _encode_cursor(offset: int) -> str:
    """Offset → opaque cursor (base64 of decimal int)."""
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


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
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin или staff_legal scope"},
        422: {"description": "Невалидный cursor / параметр"},
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
    cursor: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: AuditRepository = Depends(get_audit_repository),
) -> AdminAuditLogListResponse:
    """`GET /api/v1/admin/audit-log` (OpenAPI 04 §getAuditLog).

    Same data что и `/audit-log`, но с OpenAPI-compliant param names и
    cursor pagination. Существующий `/audit-log` остаётся для backward
    compat (используется через LEGAL middleware напрямую).

    `severity` filter — accepted но не применяется (no column; honest
    stub до landing'а severity field миграции). Response `severity`
    field = `"info"` default.
    """
    _require_staff_admin_or_legal(access_levels)

    offset = _decode_cursor(cursor)

    # Fetch limit+1 для has_more detection — стандартный паттерн.
    rows = await repo.list_records(
        actor_sub=actor_id,
        resource_type=entity_type,
        resource_id=entity_id,
        action=action,
        since=from_,
        until=to,
        q=None,
        limit=limit + 1,
        offset=offset,
    )

    has_more = len(rows) > limit
    visible = rows[:limit]
    cursor_next = _encode_cursor(offset + limit) if has_more else None
    cursor_prev = _encode_cursor(max(offset - limit, 0)) if offset > 0 else None

    entries = [AuditLogEntryView.from_model(r) for r in visible]

    return AdminAuditLogListResponse(
        data=entries,
        pagination=AdminAuditLogPagination(
            cursor_next=cursor_next,
            cursor_prev=cursor_prev,
            has_more=has_more,
            # `total_estimate` per OpenAPI «Приблизительная оценка». MVP:
            # offset + len(visible) + (1 if has_more else 0). Точный count
            # требует COUNT(*) — backlog (для admin UI достаточно
            # «есть ещё / нет ещё»).
            total_estimate=offset + len(visible) + (1 if has_more else 0),
        ),
    )


# ---------------------------------------------------------------------------
# POST /admin/audit-log/export (#239, OpenAPI 04 §exportAuditLog)


def _build_export_url(payload: AuditLogExportRequest) -> str:
    """Build result_url poking at существующий /audit-log/export.csv.

    Reuses сейчас же реализованный CSV endpoint (LEGAL gated) — frontend
    fetches result_url с тем же auth. Альтернатива (хранить blob в
    admin_tasks) — backlog когда landит async-real worker; на текущем
    sync-execution это excess complexity.

    Only `csv` format поддерживается — JSON export endpoint backlog'ом.
    Спецификация (format=json) принимается но result_url всё равно
    указывает на csv endpoint; admin UI должен handle отображение.
    """
    params: dict[str, str] = {
        "since": payload.from_.isoformat(),
        "until": payload.to.isoformat(),
    }
    # Whitelist filter keys (см. _ALLOWED_EXPORT_FILTER_KEYS).
    for key, value in payload.filters.items():
        if key in _ALLOWED_EXPORT_FILTER_KEYS and value:
            params[key] = value
    return f"/api/v1/audit-log/export.csv?{urlencode(params)}"


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
) -> AuditLogExportResponse:
    """`POST /api/v1/admin/audit-log/export` (OpenAPI 04 §exportAuditLog).

    Создаёт `admin_tasks` row + audit запись + сразу marks COMPLETED с
    result_url, указывающим на существующий `/api/v1/audit-log/export.csv`
    с теми же filters. Frontend опрашивает GET /admin/tasks/{id},
    получает result_url, делает GET для скачивания.

    Sync execution: backend сейчас не имеет worker'а; full CSV generation
    делается inline в request. Hard cap 10k rows из существующего CSV
    endpoint. Switch на real async — backlog (нужен Dramatiq + retry).

    `reason` (per OpenAPI «причина экспорта») сохраняется в task.params
    + audit metadata — это compliance trail для аудита аудит-лога.

    `filters` whitelist'ятся через `_ALLOWED_EXPORT_FILTER_KEYS` —
    unknown keys отбрасываются (anti-injection в URL).
    """
    _require_staff_admin_or_legal(access_levels)
    actor_sub = claims.get("sub", "unknown")

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
    await task_repo.mark_running(task.id)
    await task_repo.mark_completed(task.id, result_url=result_url)

    return AuditLogExportResponse(task_id=task.id, estimated_ready_at=None)


__all__ = ["router"]

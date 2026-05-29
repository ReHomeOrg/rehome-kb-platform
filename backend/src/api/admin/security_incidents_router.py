"""FastAPI router для `/api/v1/admin/security-incidents*` (#231).

OpenAPI 04 §1752-1837 — 3 endpoints:
- GET /admin/security-incidents — list с filter'ами severity / status.
- GET /admin/security-incidents/{id} — карточка.
- PATCH /admin/security-incidents/{id} — update status / resolution / РКН.

NO POST endpoint per OpenAPI — incidents создаются автоматически:
- Vault emergency unlock (ADR-0021, vault/emergency_service.py) —
  instantiates `SecurityIncident(...)` напрямую (bypass repo.create
  чтобы explicit attach FK к unlock_log) на каждый unlock event.
- `audit.security.report_security_event` (#223) — fires
  `audit.security_event` webhook на access-level escalation attempts
  (см. `articles/router.py`). NB: webhook-only, incident row не
  персистится — это observability surface; persistence wiring
  оставлен backlog'ом до решения «нужно ли вообще persist'ить escalation
  attempts отдельно от webhook'а».
- Monitoring systems / automated_scan (external) — backlog.

RBAC: staff_admin (STAFF + LEGAL) per OpenAPI «scope = staff_admin».
audit_log на update (incident lifecycle — compliance trail).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.security_incidents_repository import (
    InvalidIncidentTransitionError,
    SecurityIncidentRepository,
    get_security_incident_repository,
)
from src.api.admin.security_incidents_schemas import (
    IncidentSeverity,
    IncidentStatus,
    SecurityIncidentPagination,
    SecurityIncidentPatch,
    SecurityIncidentsListResponse,
    SecurityIncidentView,
)
from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.audit import AuditRepository, get_audit_repository
from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
    require_staff_admin,
)
from src.api.auth.scope import AccessLevel
from src.api.db import get_session
from src.api.idempotency import IdempotencyResult, process_idempotency_key

router = APIRouter(prefix="/admin/security-incidents", tags=["Admin"])


ACTION_INCIDENT_UPDATED = "admin.security_incident.updated"
RESOURCE_INCIDENT = "security_incident"


# ---------------------------------------------------------------------------
# GET /admin/security-incidents


@router.get(
    "",
    response_model=SecurityIncidentsListResponse,
    summary="Реестр security-инцидентов (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        400: {"description": "Невалидный cursor"},
    },
)
async def list_security_incidents(
    severity: IncidentSeverity | None = Query(default=None),
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=20, ge=1, le=100),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: SecurityIncidentRepository = Depends(get_security_incident_repository),
) -> SecurityIncidentsListResponse:
    """OpenAPI §listSecurityIncidents."""
    require_staff_admin(access_levels)
    decoded = decode_cursor(cursor) if cursor else None

    rows, has_more = await repo.list_filtered(
        severity=severity,
        status=status_filter,
        cursor=decoded,
        limit=limit,
    )

    cursor_next: str | None = None
    if rows and has_more:
        last = rows[-1]
        # Используем detected_at как cursor sort key (вместо updated_at —
        # для security registry chronological ordering важнее).
        cursor_next = encode_cursor(last.detected_at, last.id)

    return SecurityIncidentsListResponse(
        data=[SecurityIncidentView.model_validate(r) for r in rows],
        pagination=SecurityIncidentPagination(cursor_next=cursor_next, has_more=has_more),
    )


# ---------------------------------------------------------------------------
# GET /admin/security-incidents/{id}


@router.get(
    "/{incident_id}",
    response_model=SecurityIncidentView,
    summary="Карточка security-инцидента (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найден"},
    },
)
async def get_security_incident(
    incident_id: UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: SecurityIncidentRepository = Depends(get_security_incident_repository),
) -> SecurityIncidentView:
    """OpenAPI §getSecurityIncident."""
    require_staff_admin(access_levels)
    incident = await repo.get_by_id(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="SecurityIncident not found")
    return SecurityIncidentView.model_validate(incident)


# ---------------------------------------------------------------------------
# PATCH /admin/security-incidents/{id}


@router.patch(
    "/{incident_id}",
    response_model=SecurityIncidentView,
    summary="Обновление статуса инцидента (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найден"},
        409: {"description": "Нельзя transition из terminal status'а"},
        422: {"description": "Невалидный payload"},
    },
)
async def update_security_incident(
    payload: SecurityIncidentPatch = Body(...),
    incident_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: SecurityIncidentRepository = Depends(get_security_incident_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """OpenAPI §updateSecurityIncident.

    Updatable: status / resolution_note / rkn_notified_at. Identity-bound
    поля (incident_type / severity / detected_at / detected_by) — НЕ
    patch'аются. Empty body — no-op (no UPDATE, no audit).

    Terminal status transition (RESOLVED/FALSE_POSITIVE) — set'ит
    `resolved_at` если ещё None. Reverse (terminal → OPEN) — 409
    (incident lifecycle invariant).

    Idempotency-Key (UUID header, ADR-0025): повторный request с тем же
    key + body → replay cached response без duplicate audit row.
    """
    require_staff_admin(access_levels)

    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    incident = await repo.get_by_id(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="SecurityIncident not found")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        body = SecurityIncidentView.model_validate(incident).model_dump(mode="json")
        await idempotency.save(status_code=200, body=body)
        return JSONResponse(status_code=200, content=body)

    try:
        await repo.update(
            incident,
            status=updates.get("status"),
            resolution_note=updates.get("resolution_note"),
            rkn_notified_at=updates.get("rkn_notified_at"),
        )
    except InvalidIncidentTransitionError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await audit.record(
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_INCIDENT_UPDATED,
        resource_type=RESOURCE_INCIDENT,
        resource_id=str(incident.id),
        metadata={"updated_fields": sorted(updates.keys())},
    )
    await session.commit()
    body = SecurityIncidentView.model_validate(incident).model_dump(mode="json")
    await idempotency.save(status_code=200, body=body)
    return JSONResponse(status_code=200, content=body)


__all__ = ["router"]

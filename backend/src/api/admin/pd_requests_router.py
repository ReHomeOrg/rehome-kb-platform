"""FastAPI router для `/api/v1/admin/personal-data/requests*` (#232).

OpenAPI 04 §1642-1751 — 3 endpoints:
- GET /admin/personal-data/requests — list (filter status / type).
- GET /admin/personal-data/requests/{id} — detail.
- PATCH /admin/personal-data/requests/{id} — process (update status +
  resolution_note + attachments).

NO POST endpoint per OpenAPI — incoming ingest path (rehome.one form)
будет landed отдельным PR. `PersonalDataRequestRepository.create` API
готова.

RBAC: staff_admin (STAFF + LEGAL) per OpenAPI «scope = staff_admin».
audit_log на PATCH (compliance trail per ФЗ-152 §15).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.pd_requests_repository import (
    InvalidPdRequestTransitionError,
    PersonalDataRequestRepository,
    get_pd_request_repository,
)
from src.api.admin.pd_requests_schemas import (
    PdRequestStatus,
    PdRequestType,
    PersonalDataRequestPagination,
    PersonalDataRequestPatch,
    PersonalDataRequestsListResponse,
    PersonalDataRequestView,
)
from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.audit import AuditRepository, get_audit_repository
from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.db import get_session
from src.api.idempotency import IdempotencyResult, process_idempotency_key

router = APIRouter(prefix="/admin/personal-data/requests", tags=["Admin"])


ACTION_PD_REQUEST_UPDATED = "admin.personal_data_request.updated"
RESOURCE_PD_REQUEST = "personal_data_request"


def _require_staff_admin(access_levels: frozenset[AccessLevel]) -> None:
    if not (AccessLevel.STAFF in access_levels and AccessLevel.LEGAL in access_levels):
        raise HTTPException(
            status_code=403,
            detail="Требуется staff_admin scope",
        )


# ---------------------------------------------------------------------------
# GET /admin/personal-data/requests


@router.get(
    "",
    response_model=PersonalDataRequestsListResponse,
    summary="Заявки субъектов ПДн (ФЗ-152 §15, staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        400: {"description": "Невалидный cursor"},
    },
)
async def list_pd_requests(
    status_filter: PdRequestStatus | None = Query(default=None, alias="status"),
    type_filter: PdRequestType | None = Query(default=None, alias="type"),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=20, ge=1, le=100),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PersonalDataRequestRepository = Depends(get_pd_request_repository),
) -> PersonalDataRequestsListResponse:
    """OpenAPI §listPersonalDataRequests."""
    _require_staff_admin(access_levels)
    decoded = decode_cursor(cursor) if cursor else None

    rows, has_more = await repo.list_filtered(
        status=status_filter,
        type_filter=type_filter,
        cursor=decoded,
        limit=limit,
    )

    cursor_next: str | None = None
    if rows and has_more:
        last = rows[-1]
        # Sort key — created_at (chronological compliance review).
        cursor_next = encode_cursor(last.created_at, last.id)

    return PersonalDataRequestsListResponse(
        data=[PersonalDataRequestView.model_validate(r) for r in rows],
        pagination=PersonalDataRequestPagination(cursor_next=cursor_next, has_more=has_more),
    )


# ---------------------------------------------------------------------------
# GET /admin/personal-data/requests/{id}


@router.get(
    "/{request_id}",
    response_model=PersonalDataRequestView,
    summary="Карточка заявки субъекта ПДн (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найдена"},
    },
)
async def get_pd_request(
    request_id: UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PersonalDataRequestRepository = Depends(get_pd_request_repository),
) -> PersonalDataRequestView:
    """OpenAPI §getPersonalDataRequest."""
    _require_staff_admin(access_levels)
    req = await repo.get_by_id(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="PersonalDataRequest not found")
    return PersonalDataRequestView.model_validate(req)


# ---------------------------------------------------------------------------
# PATCH /admin/personal-data/requests/{id}


@router.patch(
    "/{request_id}",
    response_model=PersonalDataRequestView,
    summary="Обработка заявки субъекта ПДн (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найдена"},
        409: {"description": "Недопустимый transition статуса"},
        422: {"description": "Невалидный payload"},
    },
)
async def process_pd_request(
    payload: PersonalDataRequestPatch = Body(...),
    request_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PersonalDataRequestRepository = Depends(get_pd_request_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """OpenAPI §processPersonalDataRequest.

    Status — required в body. ALLOWED_MANUAL_TRANSITIONS controls valid
    paths; terminal status'ы (COMPLETED/REJECTED) auto-set completed_at.

    Transition в terminal → invariant DB CHECK обеспечивает
    completed_at NOT NULL.

    Idempotency-Key (UUID header, ADR-0025): replay cached response без
    duplicate audit row на retry.
    """
    _require_staff_admin(access_levels)

    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    req = await repo.get_by_id(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="PersonalDataRequest not found")

    updates = payload.model_dump(exclude_unset=True)
    try:
        await repo.update(
            req,
            status=updates.get("status"),
            resolution_note=updates.get("resolution_note"),
            attachments=updates.get("attachments"),
        )
    except InvalidPdRequestTransitionError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await audit.record(
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_PD_REQUEST_UPDATED,
        resource_type=RESOURCE_PD_REQUEST,
        resource_id=str(req.id),
        metadata={
            "updated_fields": sorted(updates.keys()),
            # Subject_id в audit — для compliance (кто и когда обработал
            # заявку на user X). Не sensitive — это UUID.
            "subject_id": str(req.subject_id),
        },
    )
    await session.commit()
    body = PersonalDataRequestView.model_validate(req).model_dump(mode="json")
    await idempotency.save(status_code=200, body=body)
    return JSONResponse(status_code=200, content=body)


__all__ = ["router"]

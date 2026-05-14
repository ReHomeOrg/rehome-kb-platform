"""FastAPI router для `/api/v1/audit-log` (#163).

Compliance search endpoint — ФЗ-152 Subject Access Request, forensic
review, admin "что сделал user X". STAFF / LEGAL access tier.

Audit log immutable — нет write endpoints (records создаются через
`AuditRepository.record` из других router'ов, не через эту surface).
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.audit.schemas import AuditListResponse, AuditRecordView
from src.api.auth.dependency import require_access_level, require_authenticated
from src.api.auth.scope import AccessLevel

router = APIRouter(prefix="/audit-log", tags=["Audit"])


@router.get(
    "",
    response_model=AuditListResponse,
    response_model_by_alias=False,
    summary="Search audit log (STAFF / LEGAL)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        422: {"description": "Невалидный параметр (date format etc.)"},
    },
)
async def search_audit_log(
    actor_sub: str | None = Query(default=None, max_length=200),
    resource_type: str | None = Query(default=None, max_length=32),
    resource_id: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=64),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _claims: dict[str, Any] = Depends(require_authenticated),
    # LEGAL — типичный compliance tier (юрист аудитует ФЗ-152).
    # STAFF — admin / поддержка. Любого из них достаточно.
    _legal_required: None = Depends(require_access_level(AccessLevel.LEGAL)),
    repo: AuditRepository = Depends(get_audit_repository),
) -> AuditListResponse:
    """`GET /api/v1/audit-log` — filtered search с offset pagination.

    Все фильтры optional + combined AND. Defaults — last 50 records DESC.

    Access: LEGAL tier обязателен (юрист / staff_admin / director).
    Anonymous → 401; tenant / landlord / staff_support → 403.

    Pagination — offset/limit (не cursor): audit log low-volume read,
    admin UI с jump-to-page нужнее чем consistent ordering при concurrent
    writes (audit append-only, нет risk'а tombstones).
    """
    rows = await repo.list_records(
        actor_sub=actor_sub,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return AuditListResponse(
        data=[AuditRecordView.model_validate(r) for r in rows],
        pagination={"limit": limit, "offset": offset, "count": len(rows)},
    )

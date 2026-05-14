"""FastAPI router для kb-hr (#150, PZ §7).

Все endpoints — HR_RESTRICTED tier (staff_hr / director / staff_admin
по ADR-0003). Доступ к карточкам сотрудников аудитуется per PZ §7
«Журналирование всех просмотров».
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit import (
    ACTION_HR_EMPLOYEE_ARCHIVED,
    ACTION_HR_EMPLOYEE_CREATED,
    ACTION_HR_EMPLOYEE_UPDATED,
    ACTION_HR_EMPLOYEE_VIEWED,
    RESOURCE_HR_EMPLOYEE,
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import require_access_level, require_authenticated
from src.api.auth.scope import AccessLevel
from src.api.db import get_session
from src.api.hr.repository import (
    HrEmployeeRepository,
    decode_cursor,
    encode_cursor,
    get_hr_employee_repository,
)
from src.api.hr.schemas import (
    HrEmployeeInput,
    HrEmployeeListResponse,
    HrEmployeePatch,
    HrEmployeeSummary,
    HrEmployeeView,
    PaginationInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hr/employees", tags=["HR"])


@router.get(
    "",
    response_model=HrEmployeeListResponse,
    summary="Список сотрудников (HR_RESTRICTED)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope (требуется HR_RESTRICTED)"},
        400: {"description": "Невалидный cursor"},
    },
)
async def list_employees(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=100),
    include_terminated: bool = Query(default=False),
    _claims: dict[str, Any] = Depends(require_authenticated),
    _hr: None = Depends(require_access_level(AccessLevel.HR_RESTRICTED)),
    repo: HrEmployeeRepository = Depends(get_hr_employee_repository),
) -> HrEmployeeListResponse:
    """List endpoint — summaries (без notes, чтобы не leak'ать sensitive
    HR comments в listing). Cursor stable ordering: `(updated_at, id)`.
    """
    decoded = None
    if cursor is not None:
        decoded = decode_cursor(cursor)
        if decoded is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    rows, has_more = await repo.list_active(
        cursor=decoded,
        limit=limit,
        include_terminated=include_terminated,
    )
    next_cursor: str | None = None
    if rows and has_more:
        last = rows[-1]
        next_cursor = encode_cursor(last.updated_at.isoformat(), str(last.id))

    return HrEmployeeListResponse(
        data=[HrEmployeeSummary.model_validate(r) for r in rows],
        pagination=PaginationInfo(cursor_next=next_cursor, has_more=has_more),
    )


@router.get(
    "/{employee_id}",
    response_model=HrEmployeeView,
    summary="Карточка сотрудника (HR_RESTRICTED, audited)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        404: {"description": "Сотрудник не найден"},
    },
)
async def get_employee(
    employee_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _hr: None = Depends(require_access_level(AccessLevel.HR_RESTRICTED)),
    repo: HrEmployeeRepository = Depends(get_hr_employee_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> HrEmployeeView:
    """Detail endpoint. PZ §7 — каждый просмотр карточки audit'ится."""
    emp = await repo.get_by_id(employee_id)
    if emp is None or emp.archived_at is not None:
        raise HTTPException(status_code=404, detail="Employee not found")
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_HR_EMPLOYEE_VIEWED,
        resource_type=RESOURCE_HR_EMPLOYEE,
        resource_id=str(emp.id),
    )
    await session.commit()
    return HrEmployeeView.model_validate(emp)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=HrEmployeeView,
    summary="Создать карточку сотрудника (HR_RESTRICTED)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        422: {"description": "Невалидный payload"},
    },
)
async def create_employee(
    payload: HrEmployeeInput,
    response: Response,
    claims: dict[str, Any] = Depends(require_authenticated),
    _hr: None = Depends(require_access_level(AccessLevel.HR_RESTRICTED)),
    repo: HrEmployeeRepository = Depends(get_hr_employee_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> HrEmployeeView:
    emp = await repo.create(**payload.model_dump())
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_HR_EMPLOYEE_CREATED,
        resource_type=RESOURCE_HR_EMPLOYEE,
        resource_id=str(emp.id),
        metadata={"position": emp.position, "department": emp.department},
    )
    await session.commit()
    response.headers["Location"] = f"/api/v1/hr/employees/{emp.id}"
    return HrEmployeeView.model_validate(emp)


@router.patch(
    "/{employee_id}",
    response_model=HrEmployeeView,
    summary="Partial update карточки (HR_RESTRICTED)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        404: {"description": "Сотрудник не найден"},
        422: {"description": "Невалидный payload"},
    },
)
async def patch_employee(
    employee_id: UUID = Path(...),
    payload: HrEmployeePatch = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _hr: None = Depends(require_access_level(AccessLevel.HR_RESTRICTED)),
    repo: HrEmployeeRepository = Depends(get_hr_employee_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> HrEmployeeView:
    patch_dict = payload.model_dump(exclude_none=True)
    emp = await repo.update(employee_id, patch=patch_dict)
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_HR_EMPLOYEE_UPDATED,
        resource_type=RESOURCE_HR_EMPLOYEE,
        resource_id=str(emp.id),
        metadata={"fields_changed": list(patch_dict.keys())},
    )
    await session.commit()
    return HrEmployeeView.model_validate(emp)


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Архивировать сотрудника (soft-delete, HR_RESTRICTED)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        404: {"description": "Сотрудник не найден или уже архивирован"},
    },
)
async def archive_employee(
    employee_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _hr: None = Depends(require_access_level(AccessLevel.HR_RESTRICTED)),
    repo: HrEmployeeRepository = Depends(get_hr_employee_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Soft-delete. ПЗ §7.4 — кадровые документы хранятся 50 лет (трудовые),
    archived_at marker сохраняет compliance trail без физического DROP."""
    archived = await repo.archive(employee_id)
    if not archived:
        raise HTTPException(status_code=404, detail="Employee not found")
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_HR_EMPLOYEE_ARCHIVED,
        resource_type=RESOURCE_HR_EMPLOYEE,
        resource_id=str(employee_id),
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

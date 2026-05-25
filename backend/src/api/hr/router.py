"""FastAPI router для kb-hr (#150, PZ §7).

Все endpoints — HR_RESTRICTED tier (staff_hr / director / staff_admin
по ADR-0003). Доступ к карточкам сотрудников аудитуется per PZ §7
«Журналирование всех просмотров».
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit import (
    ACTION_HR_EMPLOYEE_ARCHIVED,
    ACTION_HR_EMPLOYEE_CREATED,
    ACTION_HR_EMPLOYEE_PII_ACCESSED,
    ACTION_HR_EMPLOYEE_PII_UPDATED,
    ACTION_HR_EMPLOYEE_UPDATED,
    ACTION_HR_EMPLOYEE_VIEWED,
    RESOURCE_HR_EMPLOYEE,
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import require_access_level, require_authenticated
from src.api.auth.scope import AccessLevel
from src.api.config import Settings, get_settings
from src.api.db import get_session
from src.api.hr.crypto import decrypt_pii, encrypt_pii
from src.api.hr.models import HrEmployee
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
from src.api.idempotency import IdempotencyResult, process_idempotency_key

# Encrypted ПДн columns names (model attribute → schema attribute).
# Mapping используется для encrypt/decrypt loops в create/patch/view.
_PII_FIELDS: tuple[tuple[str, str], ...] = (
    ("passport_number", "passport_number_encrypted"),
    ("inn", "inn_encrypted"),
    ("snils", "snils_encrypted"),
    ("bank_account", "bank_account_encrypted"),
)


def _build_view(emp: HrEmployee, settings: Settings) -> HrEmployeeView:
    """Construct HrEmployeeView с decrypted ПДн plaintext."""
    data = {
        "id": emp.id,
        "user_id": emp.user_id,
        "personnel_number": emp.personnel_number,
        "full_name": emp.full_name,
        "position": emp.position,
        "department": emp.department,
        "hire_date": emp.hire_date,
        "termination_date": emp.termination_date,
        "status": emp.status,
        "contact_info": emp.contact_info,
        "notes": emp.notes,
        "created_at": emp.created_at,
        "updated_at": emp.updated_at,
        "archived_at": emp.archived_at,
    }
    for plain_attr, encrypted_attr in _PII_FIELDS:
        data[plain_attr] = decrypt_pii(getattr(emp, encrypted_attr), settings)
    return HrEmployeeView.model_validate(data)


def _split_pii_for_create(
    payload: HrEmployeeInput, settings: Settings
) -> tuple[dict[str, Any], list[str]]:
    """Split create payload в (non-pii dict, list of пии-полей which were set).

    Returns kwargs для repo.create + list ПДн полей чтобы audit log
    знал какие ПДн были set (без values — анти-leak).
    """
    base = payload.model_dump(
        exclude={f for f, _ in _PII_FIELDS},
    )
    pii_fields_touched: list[str] = []
    for plain_attr, encrypted_attr in _PII_FIELDS:
        value = getattr(payload, plain_attr)
        encrypted = encrypt_pii(value, settings)
        base[encrypted_attr] = encrypted
        if encrypted is not None:
            pii_fields_touched.append(plain_attr)
    return base, pii_fields_touched


def _split_pii_for_patch(
    payload: HrEmployeePatch, settings: Settings
) -> tuple[dict[str, Any], list[str]]:
    """Split PATCH payload в (column-keyed dict, ПДн fields list).

    Используется exclude_unset semantic: только явно переданные поля
    идут в patch dict. ПДн поля separately encrypt'аются.
    `""` (empty string) → encrypted=None → column NULL (clearing).
    """
    raw = payload.model_dump(exclude_unset=True)
    pii_fields_touched: list[str] = []
    patch_dict: dict[str, Any] = {}
    for k, v in raw.items():
        matched_pii = next((p for p in _PII_FIELDS if p[0] == k), None)
        if matched_pii is None:
            if v is not None:
                patch_dict[k] = v
            continue
        encrypted = encrypt_pii(v, settings) if v is not None else None
        patch_dict[matched_pii[1]] = encrypted
        pii_fields_touched.append(k)
    return patch_dict, pii_fields_touched


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
    settings: Settings = Depends(get_settings),
) -> HrEmployeeView:
    """Detail endpoint. PZ §7 — каждый просмотр карточки audit'ится.

    Stage 2 (#234): дополнительно audit'ится `pii_accessed` если на карточке
    есть encrypted ПДн (compliance trail per ADR-0018 §«audit log»).
    """
    emp = await repo.get_by_id(employee_id)
    if emp is None or emp.archived_at is not None:
        raise HTTPException(status_code=404, detail="Employee not found")
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_HR_EMPLOYEE_VIEWED,
        resource_type=RESOURCE_HR_EMPLOYEE,
        resource_id=str(emp.id),
    )
    # ПДн audit — fired только если карточка имеет non-null ПДн поля.
    pii_present = [plain for plain, encrypted in _PII_FIELDS if getattr(emp, encrypted) is not None]
    if pii_present:
        await audit_repo.record(
            actor_sub=claims["sub"],
            action=ACTION_HR_EMPLOYEE_PII_ACCESSED,
            resource_type=RESOURCE_HR_EMPLOYEE,
            resource_id=str(emp.id),
            metadata={"fields": pii_present},
        )
    await session.commit()
    return _build_view(emp, settings)


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
    settings: Settings = Depends(get_settings),
) -> HrEmployeeView:
    """Stage 2 (#234): ПДн поля (passport_number / inn / snils /
    bank_account) — encrypt'аются перед persisting; audit log пишет
    имена полей, не значения (анти-leak)."""
    create_kwargs, pii_fields = _split_pii_for_create(payload, settings)
    emp = await repo.create(**create_kwargs)
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_HR_EMPLOYEE_CREATED,
        resource_type=RESOURCE_HR_EMPLOYEE,
        resource_id=str(emp.id),
        metadata={"position": emp.position, "department": emp.department},
    )
    if pii_fields:
        await audit_repo.record(
            actor_sub=claims["sub"],
            action=ACTION_HR_EMPLOYEE_PII_UPDATED,
            resource_type=RESOURCE_HR_EMPLOYEE,
            resource_id=str(emp.id),
            metadata={"fields_set": pii_fields, "via": "POST"},
        )
    await session.commit()
    response.headers["Location"] = f"/api/v1/hr/employees/{emp.id}"
    return _build_view(emp, settings)


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
    settings: Settings = Depends(get_settings),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """Stage 2 (#234): ПДн поля encrypt'аются; clearing через пустую
    строку. Audit pii_updated с именами полей (без значений).

    Idempotency-Key (UUID header, ADR-0025): replay cached response без
    duplicate audit / pii_updated row.
    """
    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    patch_dict, pii_fields = _split_pii_for_patch(payload, settings)
    emp = await repo.update(employee_id, patch=patch_dict)
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    # Separate audit events: regular update + pii update (compliance —
    # pii operations должны быть identifiable в audit query без JSONB
    # introspection).
    non_pii_changed = [k for k in patch_dict if k not in {f for _, f in _PII_FIELDS}]
    if non_pii_changed:
        await audit_repo.record(
            actor_sub=claims["sub"],
            action=ACTION_HR_EMPLOYEE_UPDATED,
            resource_type=RESOURCE_HR_EMPLOYEE,
            resource_id=str(emp.id),
            metadata={"fields_changed": sorted(non_pii_changed)},
        )
    if pii_fields:
        await audit_repo.record(
            actor_sub=claims["sub"],
            action=ACTION_HR_EMPLOYEE_PII_UPDATED,
            resource_type=RESOURCE_HR_EMPLOYEE,
            resource_id=str(emp.id),
            metadata={"fields_set": sorted(pii_fields), "via": "PATCH"},
        )
    await session.commit()
    body = _build_view(emp, settings).model_dump(mode="json")
    await idempotency.save(status_code=200, body=body)
    return JSONResponse(status_code=200, content=body)


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

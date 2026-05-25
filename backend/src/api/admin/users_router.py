"""FastAPI router для `/api/v1/admin/users*` (#230, OpenAPI 04 §1334-1506).

5 endpoints:
- GET `/admin/users` — list с фильтрами role / status + cursor pagination.
- POST `/admin/users` — create new KB staff user (Idempotency-Key support).
- GET `/admin/users/{user_id}` — карточка.
- PATCH `/admin/users/{user_id}` — partial update (role / status /
  permissions / mfa / last_login).
- DELETE `/admin/users/{user_id}` — soft-delete (status=ARCHIVED).

RBAC: все endpoints требуют staff_admin (STAFF + LEGAL) per OpenAPI.

Audit: создание / update / deactivate → audit_log.

OpenAPI говорит «Здесь — сотрудники с правами редактирования, проверяющие,
администраторы». НЕ replaces Keycloak — это metadata layer; Sync с КС
(last_login / mfa_enabled mirror) — backlog.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.users_repository import (
    KbUserRepository,
    get_kb_user_repository,
)
from src.api.admin.users_schemas import (
    KbUserCreate,
    KbUserPatch,
    KbUserRole,
    KbUsersListResponse,
    KbUsersPagination,
    KbUserStatus,
    KbUserView,
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

router = APIRouter(prefix="/admin/users", tags=["Admin"])


# Audit action constants — kb_users namespace (новые actions; не пересекаются
# с collaborator / hr actions из существующих модулей).
ACTION_KB_USER_CREATED = "admin.kb_user.created"
ACTION_KB_USER_UPDATED = "admin.kb_user.updated"
ACTION_KB_USER_DEACTIVATED = "admin.kb_user.deactivated"
RESOURCE_KB_USER = "kb_user"


def _require_staff_admin(access_levels: frozenset[AccessLevel]) -> None:
    """staff_admin (STAFF + LEGAL) per OpenAPI «scope = staff_admin».

    staff_support / staff_hr → 403.
    """
    if not (AccessLevel.STAFF in access_levels and AccessLevel.LEGAL in access_levels):
        raise HTTPException(
            status_code=403,
            detail="Требуется staff_admin scope",
        )


# ---------------------------------------------------------------------------
# GET /admin/users


@router.get(
    "",
    response_model=KbUsersListResponse,
    summary="Список kb-пользователей (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        400: {"description": "Невалидный cursor"},
    },
)
async def list_kb_users(
    role: KbUserRole | None = Query(default=None),
    status_filter: KbUserStatus | None = Query(default=None, alias="status"),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=20, ge=1, le=100),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: KbUserRepository = Depends(get_kb_user_repository),
) -> KbUsersListResponse:
    """`GET /api/v1/admin/users` per OpenAPI §listKbUsers.

    Filters role / status — optional. Cursor — opaque base64-encoded
    `(updated_at, id)` для keyset pagination (стандартный pattern).
    """
    _require_staff_admin(access_levels)

    decoded = decode_cursor(cursor) if cursor else None

    rows, has_more = await repo.list_filtered(
        role=role,
        status=status_filter,
        cursor=decoded,
        limit=limit,
    )

    cursor_next: str | None = None
    if rows and has_more:
        last = rows[-1]
        cursor_next = encode_cursor(last.updated_at, last.id)

    return KbUsersListResponse(
        data=[KbUserView.model_validate(u) for u in rows],
        pagination=KbUsersPagination(cursor_next=cursor_next, has_more=has_more),
    )


# ---------------------------------------------------------------------------
# POST /admin/users


@router.post(
    "",
    response_model=KbUserView,
    status_code=status.HTTP_201_CREATED,
    summary="Создать kb-пользователя (staff_admin)",
    responses={
        201: {"description": "Создан"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        409: {"description": "Email уже используется (case-insensitive)"},
        422: {"description": "Невалидный payload"},
    },
)
async def create_kb_user(
    payload: KbUserCreate,
    response: Response,
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: KbUserRepository = Depends(get_kb_user_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """`POST /api/v1/admin/users` per OpenAPI §createKbUser.

    Idempotency-Key supported (E5.1 pattern): replay → cached response.

    Email unique CASE-INSENSITIVELY (BD UQ on `lower(email)`); duplicate → 409.
    """
    _require_staff_admin(access_levels)

    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    try:
        user = await repo.create(
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role,
            permissions=payload.permissions,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Email already registered (case-insensitive match)",
        ) from exc

    await audit.record(
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_KB_USER_CREATED,
        resource_type=RESOURCE_KB_USER,
        resource_id=str(user.id),
        metadata={
            "email": user.email,
            "role": user.role,
            "permissions": list(user.permissions),
        },
    )
    await session.commit()

    location = f"/api/v1/admin/users/{user.id}"
    response.headers["Location"] = location

    body = KbUserView.model_validate(user).model_dump(mode="json")
    await idempotency.save(
        status_code=status.HTTP_201_CREATED,
        body=body,
        headers={"Location": location},
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=body,
        headers={"Location": location},
    )


# ---------------------------------------------------------------------------
# GET /admin/users/{user_id}


@router.get(
    "/{user_id}",
    response_model=KbUserView,
    summary="Карточка kb-пользователя (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найден"},
    },
)
async def get_kb_user(
    user_id: UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: KbUserRepository = Depends(get_kb_user_repository),
) -> KbUserView:
    _require_staff_admin(access_levels)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="KbUser not found")
    return KbUserView.model_validate(user)


# ---------------------------------------------------------------------------
# PATCH /admin/users/{user_id}


@router.patch(
    "/{user_id}",
    response_model=KbUserView,
    summary="Изменить роль/права/статус kb-пользователя (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найден"},
        422: {"description": "Невалидный payload"},
    },
)
async def update_kb_user(
    payload: KbUserPatch = Body(...),
    user_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: KbUserRepository = Depends(get_kb_user_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """PATCH per OpenAPI §updateKbUser.

    Partial update: только переданные поля попадают в SQL UPDATE.
    Empty body (всё None) — no-op (idempotent), audit row не пишется.

    Idempotency-Key (UUID header, ADR-0025): повторный request с тем же
    key + body → replay cached response без duplicate audit row.
    """
    _require_staff_admin(access_levels)

    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="KbUser not found")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        body = KbUserView.model_validate(user).model_dump(mode="json")
        await idempotency.save(status_code=200, body=body)
        return JSONResponse(status_code=200, content=body)

    await repo.update_fields(user, updates)
    await audit.record(
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_KB_USER_UPDATED,
        resource_type=RESOURCE_KB_USER,
        resource_id=str(user.id),
        metadata={"updated_fields": sorted(updates.keys())},
    )
    await session.commit()
    body = KbUserView.model_validate(user).model_dump(mode="json")
    await idempotency.save(status_code=200, body=body)
    return JSONResponse(status_code=200, content=body)


# ---------------------------------------------------------------------------
# DELETE /admin/users/{user_id}


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Деактивировать kb-пользователя (staff_admin)",
    responses={
        204: {"description": "Деактивирован (status=ARCHIVED)"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найден"},
    },
)
async def deactivate_kb_user(
    user_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: KbUserRepository = Depends(get_kb_user_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Soft-delete: status → ARCHIVED + audit log entry.

    Idempotent: повторный DELETE на ARCHIVED → 204 (нет audit row при no-op).
    """
    _require_staff_admin(access_levels)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="KbUser not found")

    was_active = user.status != "ARCHIVED"
    await repo.deactivate(user)
    if was_active:
        await audit.record(
            actor_sub=str(claims.get("sub", "unknown")),
            action=ACTION_KB_USER_DEACTIVATED,
            resource_type=RESOURCE_KB_USER,
            resource_id=str(user.id),
            metadata={
                "email": user.email,
                "previous_status": "ACTIVE",
                "deactivated_at": datetime.now(UTC).isoformat(),
            },
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]

"""Admin CRUD router /admin/categories (ADR-0024, #355).

4 endpoints:
- POST   /admin/categories          — create.
- GET    /admin/categories/{id}     — карточка (admin видит archived тоже).
- PATCH  /admin/categories/{id}     — update title/description/parent_id
  (slug READ-ONLY per ADR Open Q 2).
- DELETE /admin/categories/{id}     — soft-delete (archived_at).

RBAC: staff_admin (STAFF + LEGAL). БЕЗ step-up MFA per ADR Open Q 3 —
categories не security-sensitive (admin taxonomy).

Cycle detection — app-level в `CategoryAdminRepository._assert_no_cycle`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit.actions import (
    ACTION_ADMIN_CATEGORY_ARCHIVED,
    ACTION_ADMIN_CATEGORY_CREATED,
    ACTION_ADMIN_CATEGORY_UPDATED,
    RESOURCE_ADMIN_CATEGORY,
)
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
    require_staff_admin,
)
from src.api.auth.scope import AccessLevel
from src.api.categories.admin_repository import (
    ArchivedParentError,
    CategoryAdminRepository,
    CycleDetectedError,
    ParentNotFoundError,
    SlugConflictError,
    get_category_admin_repository,
)
from src.api.categories.admin_schemas import (
    CategoryCreate,
    CategoryPatch,
    CategoryView,
)
from src.api.db import get_session
from src.api.idempotency import IdempotencyResult, process_idempotency_key

router = APIRouter(prefix="/admin/categories", tags=["Admin"])


# ---------------------------------------------------------------------------
# POST /admin/categories


@router.post(
    "",
    response_model=CategoryView,
    status_code=status.HTTP_201_CREATED,
    summary="Создать категорию (staff_admin)",
    responses={
        201: {"description": "Создана"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        409: {"description": "Slug уже занят"},
        422: {"description": "Невалидный payload / unknown parent_id"},
    },
)
async def create_category(
    payload: CategoryCreate,
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: CategoryAdminRepository = Depends(get_category_admin_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """ADR-0024 §POST /admin/categories.

    Slug — immutable identifier (post-create нельзя rename).
    parent_id optional — None = root. Archived parent → 422.

    Idempotency-Key (UUID header, ADR-0025) — поддержан.
    """
    require_staff_admin(access_levels)

    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    actor_sub = str(claims.get("sub", "unknown"))
    try:
        category = await repo.create(
            slug=payload.slug,
            title=payload.title,
            description=payload.description,
            parent_id=payload.parent_id,
        )
    except SlugConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ParentNotFoundError, ArchivedParentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await audit.record(
        actor_sub=actor_sub,
        action=ACTION_ADMIN_CATEGORY_CREATED,
        resource_type=RESOURCE_ADMIN_CATEGORY,
        resource_id=str(category.id),
        metadata={
            "slug": category.slug,
            "parent_id": str(category.parent_id) if category.parent_id else None,
        },
    )
    await session.commit()

    body = CategoryView.model_validate(category).model_dump(mode="json")
    await idempotency.save(status_code=status.HTTP_201_CREATED, body=body)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=body)


# ---------------------------------------------------------------------------
# GET /admin/categories/{id}


@router.get(
    "/{category_id}",
    response_model=CategoryView,
    summary="Карточка категории (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найдена"},
    },
)
async def get_category(
    category_id: UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: CategoryAdminRepository = Depends(get_category_admin_repository),
) -> CategoryView:
    """Admin видит row даже если archived (toggle filter в UI на client-side)."""
    require_staff_admin(access_levels)
    category = await repo.get_by_id(category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return CategoryView.model_validate(category)


# ---------------------------------------------------------------------------
# PATCH /admin/categories/{id}


@router.patch(
    "/{category_id}",
    response_model=CategoryView,
    summary="Обновить категорию (staff_admin)",
    responses={
        200: {"description": "Обновлено"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найдена"},
        422: {"description": "Cycle / unknown parent_id / archived parent"},
    },
)
async def update_category(
    payload: CategoryPatch = Body(...),
    category_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: CategoryAdminRepository = Depends(get_category_admin_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """PATCH editable fields: title / description / parent_id. Slug
    READ-ONLY (см. ADR-0024 §Open Q 2).

    Cycle detection: PATCH parent_id walks parent chain — collision с
    current id → 422.

    Idempotency-Key (UUID header, ADR-0025) — поддержан.
    """
    require_staff_admin(access_levels)

    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    category = await repo.get_by_id(category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        body = CategoryView.model_validate(category).model_dump(mode="json")
        await idempotency.save(status_code=200, body=body)
        return JSONResponse(status_code=200, content=body)

    try:
        await repo.update(
            category,
            title=updates.get("title"),
            description=updates.get("description"),
            parent_id=updates.get("parent_id"),
            parent_id_set="parent_id" in updates,
        )
    except (ParentNotFoundError, ArchivedParentError, CycleDetectedError) as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await audit.record(
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_ADMIN_CATEGORY_UPDATED,
        resource_type=RESOURCE_ADMIN_CATEGORY,
        resource_id=str(category.id),
        metadata={"updated_fields": sorted(updates.keys())},
    )
    await session.commit()

    body = CategoryView.model_validate(category).model_dump(mode="json")
    await idempotency.save(status_code=200, body=body)
    return JSONResponse(status_code=200, content=body)


# ---------------------------------------------------------------------------
# DELETE /admin/categories/{id}


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Архивировать категорию (soft-delete, staff_admin)",
    responses={
        204: {"description": "Архивирована"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        404: {"description": "Не найдена"},
    },
)
async def archive_category(
    category_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: CategoryAdminRepository = Depends(get_category_admin_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Soft-delete: archived_at = now(). Articles с
    `articles.category = <slug>` остаются (orphan reference acceptable
    per ADR-0024 Вариант B). Idempotent — повторный DELETE → 204 no-op.

    DELETE per ADR-0025 не использует idempotency-key (natural 404 + idempotent
    archive semantics).
    """
    require_staff_admin(access_levels)
    category = await repo.get_by_id(category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    was_active = category.archived_at is None
    await repo.archive(category)
    if was_active:
        await audit.record(
            actor_sub=str(claims.get("sub", "unknown")),
            action=ACTION_ADMIN_CATEGORY_ARCHIVED,
            resource_type=RESOURCE_ADMIN_CATEGORY,
            resource_id=str(category.id),
            metadata={"slug": category.slug},
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]

"""FastAPI router для `/api/v1/service-orders/*` (ТЗ §3.10.6, #224).

7 endpoint'ов:
- `GET /service-orders` — list (customer's own или staff filter).
- `POST /service-orders` — create (idempotent через Idempotency-Key).
- `GET /service-orders/{id}` — карточка (owner-or-staff).
- `POST /service-orders/{id}/cancel` — отмена (owner-or-staff).
- `POST /service-orders/{id}/accept` — accept (staff-only MVP; #329).
- `POST /service-orders/{id}/complete` — completion (staff-only MVP; #329).
- `POST /service-orders/{id}/fail` — failure (staff-only MVP; #329).

Per ТЗ §3.10.6: «Деньги пользователя удерживаются в эскроу» — payment
flow OUT OF SCOPE этого PR (Architect deferred). Создание order'а
ставит `payment_status='HOLD'` placeholder без реального hold'а.

Webhook events (ТЗ §5.1) — все 5 lifecycle events wired:
- create → `service_order.created`
- accept → `service_order.accepted` (#329)
- complete → `service_order.completed` (#329)
- fail → `service_order.failed` (#329)
- cancel → `service_order.cancelled`

RBAC на accept/complete/fail — staff-only до landing'а collaborator-side
auth (partner CRM integration). После landing'а — расширится на owner
collaborator (по `collaborator_id` order'а).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.collaborators.service_orders_models import ServiceOrder
from src.api.collaborators.service_orders_repository import (
    InvalidStatusTransitionError,
    ServiceOrderRepository,
    get_service_order_repository,
)
from src.api.collaborators.service_orders_schemas import (
    ServiceOrderCancelInput,
    ServiceOrderInput,
    ServiceOrderListResponse,
    ServiceOrderResponse,
    ServiceOrderStatus,
    ServiceOrderTransitionInput,
)
from src.api.db import get_session
from src.api.idempotency import IdempotencyResult, process_idempotency_key
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)
from src.api.webhooks.events import WebhookEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/service-orders", tags=["Collaborators"])


def _is_staff(access_levels: frozenset[AccessLevel]) -> bool:
    """STAFF+ scope → видит все заказы. Tenant/landlord/anon — только свои.

    Anon — falls back в `customer_sub`-фильтр, в практике anon не имеет
    JWT sub → 401 раньше через `require_authenticated`.
    """
    return bool(access_levels & {AccessLevel.STAFF, AccessLevel.LEGAL, AccessLevel.HR_RESTRICTED})


def _serialize(order: ServiceOrder) -> dict[str, Any]:
    """ServiceOrder → response dict с `customer_id` alias (OpenAPI)."""
    return ServiceOrderResponse.model_validate(order).model_dump(mode="json", by_alias=True)


async def _dispatch_lifecycle_event(
    dispatcher: WebhookEventDispatcher,
    *,
    event: WebhookEvent,
    order: ServiceOrder,
) -> None:
    """Fire service_order.* webhook. Payload содержит минимум для routing
    у subscriber'а: id + collaborator + customer_sub + status + price.

    customer_sub — Keycloak UUID, не ПДн в смысле ФЗ-152 (opaque identity).
    Цены — internal операционные данные, не масковать subscribed clients.
    """
    await dispatcher.dispatch(
        event_type=event.value,
        payload={
            "order_id": str(order.id),
            "collaborator_id": str(order.collaborator_id),
            "customer_sub": order.customer_sub,
            "service_type": order.service_type,
            "status": order.status,
            "payment_status": order.payment_status,
            "price_rub": str(order.price_rub) if order.price_rub is not None else None,
            "updated_at": order.updated_at.isoformat(),
        },
    )


@router.get(
    "",
    response_model=ServiceOrderListResponse,
    summary="Заказы услуг (tenant/landlord — свои, staff — все)",
)
async def list_service_orders(
    collaborator_id: UUID | None = Query(default=None),
    status_filter: ServiceOrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ServiceOrderRepository = Depends(get_service_order_repository),
) -> ServiceOrderListResponse:
    """`GET /service-orders` per ТЗ §3.10.6.

    Customer view: только заказы где `customer_sub == jwt.sub`.
    Staff view: все, с опциональными `collaborator_id` / `status` filter'ами.

    Сортировка: `created_at DESC` (newest first).
    """
    rows = await repo.list_for_actor(
        actor_sub=claims["sub"],
        is_staff=_is_staff(access_levels),
        collaborator_id=collaborator_id,
        status=status_filter,
        limit=limit,
    )
    return ServiceOrderListResponse(data=[ServiceOrderResponse.model_validate(o) for o in rows])


@router.post(
    "",
    response_model=ServiceOrderResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Создать заказ услуги",
    responses={
        401: {"description": "Не аутентифицирован"},
        409: {"description": "Idempotency-Key replay с другим body"},
        422: {"description": "Невалидный payload"},
        500: {"description": "FK violation (несуществующий collaborator/premises)"},
    },
)
async def create_service_order(
    payload: ServiceOrderInput,
    response: Response,
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: ServiceOrderRepository = Depends(get_service_order_repository),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> Any:
    """`POST /service-orders` per ТЗ §3.10.6.

    Status default = PENDING_COLLABORATOR (sent to коллаборанту для
    accept). DRAFT в API не создаётся (внутренний state).

    `customer_sub` — JWT sub authenticated user'а, не из payload
    (anti-spoofing). Идемпотентность по `Idempotency-Key` — повтор с
    тем же body → cached response (Stripe pattern).

    Payment status — `HOLD` placeholder. Реальный escrow flow —
    отдельный PR (Architect deferred per memory item 2).
    """
    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    try:
        order = await repo.create(
            collaborator_id=payload.collaborator_id,
            customer_sub=claims["sub"],
            service_type=payload.service_type,
            premises_id=payload.premises_id,
            booking_id=payload.booking_id,
            service_description=payload.service_description,
            scheduled_at=payload.scheduled_at,
            customer_notes=payload.customer_notes,
            price_rub=payload.price_rub,
            commission_rub=payload.commission_rub,
        )
        # ADR-0026 Slice 3: dispatch ДО commit'а → atomic order + outbox.
        await _dispatch_lifecycle_event(
            webhook_dispatcher,
            event=WebhookEvent.SERVICE_ORDER_CREATED,
            order=order,
        )
        await session.commit()
    except IntegrityError as exc:
        # Несуществующий collaborator / premises — FK violation. 422 более
        # honest чем 500: caller передал bad UUID. Без echo'я server detail
        # (FZ-152 / security).
        await session.rollback()
        logger.warning("service_orders.create.fk_violation", exc_info=exc)
        raise HTTPException(
            status_code=422,
            detail="Referenced collaborator or premises not found",
        ) from exc

    location = f"/api/v1/service-orders/{order.id}"
    response.headers["Location"] = location

    body = _serialize(order)
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


@router.get(
    "/{order_id}",
    response_model=ServiceOrderResponse,
    response_model_by_alias=True,
    summary="Карточка заказа",
    responses={
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Не найдено или нет доступа"},
    },
)
async def get_service_order(
    order_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ServiceOrderRepository = Depends(get_service_order_repository),
) -> ServiceOrderResponse:
    """`GET /service-orders/{id}`.

    404-mask для non-owner non-staff: запрос вне scope → 404, не 403
    (ADR-0003 pattern).
    """
    order = await repo.get_for_actor(
        order_id,
        actor_sub=claims["sub"],
        is_staff=_is_staff(access_levels),
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Service order not found")
    return ServiceOrderResponse.model_validate(order)


@router.post(
    "/{order_id}/cancel",
    response_model=ServiceOrderResponse,
    response_model_by_alias=True,
    summary="Отмена заказа",
    responses={
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Не найдено или нет доступа"},
        409: {"description": "Заказ нельзя отменить в текущем status"},
    },
)
async def cancel_service_order(
    order_id: UUID = Path(...),
    payload: ServiceOrderCancelInput | None = Body(default=None),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ServiceOrderRepository = Depends(get_service_order_repository),
    session: AsyncSession = Depends(get_session),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> ServiceOrderResponse:
    """`POST /service-orders/{id}/cancel` per ТЗ §3.10.6.

    Right-to-cancel: customer (owner) и staff. Per ТЗ — возврат средств
    зависит от стадии (правила коллаборанта); refund flow — отдельный
    PR с escrow logic. MVP только меняет status + cancel_reason.
    """
    order = await repo.get_for_actor(
        order_id,
        actor_sub=claims["sub"],
        is_staff=_is_staff(access_levels),
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Service order not found")

    reason = payload.reason if payload is not None else None
    try:
        cancelled = await repo.cancel(order, reason=reason)
    except InvalidStatusTransitionError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # ADR-0026 Slice 3: dispatch ДО commit'а → atomic.
    await _dispatch_lifecycle_event(
        webhook_dispatcher,
        event=WebhookEvent.SERVICE_ORDER_CANCELLED,
        order=cancelled,
    )
    await session.commit()
    return ServiceOrderResponse.model_validate(cancelled)


async def _staff_only_transition(
    *,
    order_id: UUID,
    to_status: str,
    event: WebhookEvent,
    payload: ServiceOrderTransitionInput | None,
    claims: dict[str, Any],
    access_levels: frozenset[AccessLevel],
    repo: ServiceOrderRepository,
    session: AsyncSession,
    webhook_dispatcher: WebhookEventDispatcher,
) -> ServiceOrderResponse:
    """Shared body для accept / complete / fail endpoints.

    RBAC: staff-only до landing'а partner auth (см. модуль docstring).
    404-mask non-staff (consistent с другими out-of-scope endpoints).
    """
    if not _is_staff(access_levels):
        raise HTTPException(status_code=403, detail="staff-only operation")
    order = await repo.get_for_actor(order_id, actor_sub=claims["sub"], is_staff=True)
    if order is None:
        raise HTTPException(status_code=404, detail="Service order not found")

    notes = payload.notes if payload is not None else None
    try:
        updated = await repo.transition(order, to_status=to_status, notes=notes)
    except InvalidStatusTransitionError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # ADR-0026 Slice 3: dispatch ДО commit'а → atomic.
    await _dispatch_lifecycle_event(webhook_dispatcher, event=event, order=updated)
    await session.commit()
    return ServiceOrderResponse.model_validate(updated)


@router.post(
    "/{order_id}/accept",
    response_model=ServiceOrderResponse,
    response_model_by_alias=True,
    summary="Принять заказ (staff-only MVP)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff scope"},
        404: {"description": "Не найдено"},
        409: {"description": "Невалидный переход состояния"},
    },
)
async def accept_service_order(
    order_id: UUID = Path(...),
    payload: ServiceOrderTransitionInput | None = Body(default=None),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ServiceOrderRepository = Depends(get_service_order_repository),
    session: AsyncSession = Depends(get_session),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> ServiceOrderResponse:
    """`POST /service-orders/{id}/accept` — PENDING_COLLABORATOR → ACCEPTED."""
    return await _staff_only_transition(
        order_id=order_id,
        to_status="ACCEPTED",
        event=WebhookEvent.SERVICE_ORDER_ACCEPTED,
        payload=payload,
        claims=claims,
        access_levels=access_levels,
        repo=repo,
        session=session,
        webhook_dispatcher=webhook_dispatcher,
    )


@router.post(
    "/{order_id}/complete",
    response_model=ServiceOrderResponse,
    response_model_by_alias=True,
    summary="Завершить заказ (staff-only MVP)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff scope"},
        404: {"description": "Не найдено"},
        409: {"description": "Невалидный переход состояния"},
    },
)
async def complete_service_order(
    order_id: UUID = Path(...),
    payload: ServiceOrderTransitionInput | None = Body(default=None),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ServiceOrderRepository = Depends(get_service_order_repository),
    session: AsyncSession = Depends(get_session),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> ServiceOrderResponse:
    """`POST /service-orders/{id}/complete` — ACCEPTED | IN_PROGRESS → COMPLETED."""
    return await _staff_only_transition(
        order_id=order_id,
        to_status="COMPLETED",
        event=WebhookEvent.SERVICE_ORDER_COMPLETED,
        payload=payload,
        claims=claims,
        access_levels=access_levels,
        repo=repo,
        session=session,
        webhook_dispatcher=webhook_dispatcher,
    )


@router.post(
    "/{order_id}/fail",
    response_model=ServiceOrderResponse,
    response_model_by_alias=True,
    summary="Зафиксировать неудачу заказа (staff-only MVP)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff scope"},
        404: {"description": "Не найдено"},
        409: {"description": "Невалидный переход состояния"},
    },
)
async def fail_service_order(
    order_id: UUID = Path(...),
    payload: ServiceOrderTransitionInput | None = Body(default=None),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ServiceOrderRepository = Depends(get_service_order_repository),
    session: AsyncSession = Depends(get_session),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> ServiceOrderResponse:
    """`POST /service-orders/{id}/fail` — PENDING | ACCEPTED | IN_PROGRESS → FAILED."""
    return await _staff_only_transition(
        order_id=order_id,
        to_status="FAILED",
        event=WebhookEvent.SERVICE_ORDER_FAILED,
        payload=payload,
        claims=claims,
        access_levels=access_levels,
        repo=repo,
        session=session,
        webhook_dispatcher=webhook_dispatcher,
    )


__all__ = ["router"]

"""ServiceOrderRepository (ТЗ §3.10.6 / #224).

CRUD + scope-aware visibility:
- Customer (tenant/landlord): видит только свои (`customer_sub == jwt.sub`).
- Staff: видит все.

Ordering: `created_at DESC, id DESC` — newest first, deterministic tie-break.

Out-of-scope row → return None (404 mask, ADR-0003 pattern). Cancel /
status transitions wrap'ятся в state-machine validation (см.
`service_orders_models.ALLOWED_TRANSITIONS`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.collaborators.service_orders_models import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    ServiceOrder,
)
from src.api.db import get_session


class InvalidStatusTransitionError(Exception):
    """Caller пытается перейти в state не из `ALLOWED_TRANSITIONS[current]`."""


class ServiceOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        collaborator_id: UUID,
        customer_sub: str,
        service_type: str,
        premises_id: UUID | None = None,
        booking_id: UUID | None = None,
        service_description: str | None = None,
        scheduled_at: datetime | None = None,
        customer_notes: str | None = None,
        price_rub: object | None = None,
        commission_rub: object | None = None,
    ) -> ServiceOrder:
        """INSERT новый заказ. Status = 'PENDING_COLLABORATOR' (default
        DRAFT для backend-internal drafts, но API create — сразу
        actionable).

        Caller commit'ит (Repository pattern — ADR-0008).
        """
        order = ServiceOrder(
            collaborator_id=collaborator_id,
            customer_sub=customer_sub,
            premises_id=premises_id,
            booking_id=booking_id,
            service_type=service_type,
            service_description=service_description,
            scheduled_at=scheduled_at,
            status="PENDING_COLLABORATOR",
            price_rub=price_rub,
            commission_rub=commission_rub,
            customer_notes=customer_notes,
            payment_status="HOLD",
        )
        self._session.add(order)
        await self._session.flush()
        await self._session.refresh(order)
        return order

    async def get_for_actor(
        self,
        order_id: UUID,
        *,
        actor_sub: str,
        is_staff: bool,
    ) -> ServiceOrder | None:
        """Owner-or-staff fetch. Non-staff видит только свои заказы
        (`customer_sub == actor_sub`); out-of-scope → None (404 mask).
        """
        stmt = select(ServiceOrder).where(ServiceOrder.id == order_id)
        if not is_staff:
            stmt = stmt.where(ServiceOrder.customer_sub == actor_sub)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_actor(
        self,
        *,
        actor_sub: str,
        is_staff: bool,
        collaborator_id: UUID | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[ServiceOrder]:
        """List orders с фильтрами. Non-staff — только свои. Staff — все.

        Cursor pagination — backlog (MVP: simple `LIMIT N`, sorted
        newest first).
        """
        stmt = select(ServiceOrder)
        if not is_staff:
            stmt = stmt.where(ServiceOrder.customer_sub == actor_sub)
        if collaborator_id is not None:
            stmt = stmt.where(ServiceOrder.collaborator_id == collaborator_id)
        if status is not None:
            stmt = stmt.where(ServiceOrder.status == status)
        stmt = stmt.order_by(ServiceOrder.created_at.desc(), ServiceOrder.id.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def cancel(
        self,
        order: ServiceOrder,
        *,
        reason: str | None,
    ) -> ServiceOrder:
        """Transition в CANCELLED + set completed_at + cancel_reason.

        Raises InvalidStatusTransitionError если текущий status —
        terminal (CANCELLED/COMPLETED/FAILED). Per `ALLOWED_TRANSITIONS`
        некоторые non-terminal states тоже не могут cancel (но в MVP все
        non-terminal могут → cancel).
        """
        if "CANCELLED" not in ALLOWED_TRANSITIONS.get(order.status, frozenset()):
            raise InvalidStatusTransitionError(f"Cannot cancel order in status={order.status}")
        order.status = "CANCELLED"
        order.cancel_reason = reason
        order.completed_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(order)
        return order


def get_service_order_repository(
    session: AsyncSession = Depends(get_session),
) -> ServiceOrderRepository:
    return ServiceOrderRepository(session)


__all__ = [
    "InvalidStatusTransitionError",
    "ServiceOrderRepository",
    "TERMINAL_STATUSES",
    "get_service_order_repository",
]

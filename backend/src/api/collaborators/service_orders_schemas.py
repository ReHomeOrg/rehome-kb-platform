"""Pydantic schemas для ServiceOrders (ТЗ §3.10.6 / #224).

OpenAPI 04 `ServiceOrderInput`, `ServiceOrder`, `ServiceOrderStatus`.

Денежные поля (`price_rub`, `commission_rub`) — passthrough из payload
(non-negative validation на API boundary). Architect deferred "service
payment sizing" — backend не вычисляет ни цену, ни комиссию; они
приходят от caller'а (staff /admin/order draft tool, partner CRM
integration) и persist'ятся as-is.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ServiceOrderStatus = Literal[
    "DRAFT",
    "PENDING_COLLABORATOR",
    "ACCEPTED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    "FAILED",
    "DISPUTED",
]

PaymentStatus = Literal["HOLD", "PAID", "REFUNDED", "PARTIAL_REFUND"]


class ServiceOrderInput(BaseModel):
    """POST `/api/v1/service-orders` body.

    `service_type` — free-text per OpenAPI (taxonomy на стороне коллаборанта
    / staff curation). MVP не enforce'ит enum — backlog когда landed'ится
    каталог услуг.
    """

    model_config = ConfigDict(extra="forbid")

    collaborator_id: UUID
    premises_id: UUID | None = None
    booking_id: UUID | None = None
    service_type: str = Field(min_length=1, max_length=100)
    service_description: str | None = Field(default=None, max_length=2000)
    scheduled_at: datetime | None = None
    customer_notes: str | None = Field(default=None, max_length=2000)
    # Денежные поля — opt-in (caller staff/CRM передаёт явно). Валидация
    # non-negative; precision: 12,2 (до 9_999_999_999.99 руб.).
    price_rub: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    commission_rub: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )


class ServiceOrderCancelInput(BaseModel):
    """POST `/api/v1/service-orders/{id}/cancel` body (optional)."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class ServiceOrderResponse(BaseModel):
    """OpenAPI 04 `ServiceOrder` schema response."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    collaborator_id: UUID
    # `customer_id` per OpenAPI — мы хранам JWT sub в `customer_sub`; для
    # внешнего contract'а exposed как `customer_id` (UUID-shaped string).
    customer_sub: str = Field(serialization_alias="customer_id")
    premises_id: UUID | None
    booking_id: UUID | None
    service_type: str
    service_description: str | None
    scheduled_at: datetime | None
    status: ServiceOrderStatus
    price_rub: Decimal | None
    commission_rub: Decimal | None
    payment_status: PaymentStatus
    customer_notes: str | None
    collaborator_notes: str | None
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ServiceOrderListResponse(BaseModel):
    """GET `/api/v1/service-orders` envelope."""

    data: list[ServiceOrderResponse]


__all__ = [
    "PaymentStatus",
    "ServiceOrderCancelInput",
    "ServiceOrderInput",
    "ServiceOrderListResponse",
    "ServiceOrderResponse",
    "ServiceOrderStatus",
]

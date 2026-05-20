"""ServiceOrder ORM model (ТЗ §3.10.6 / #224).

State machine + payment status — фиксированные tuple'ы, mirror'ятся
в migration CHECK constraints через `test_service_orders_check_sync`.
Drift = test fail.

ВАЖНО: payment_status transitions deferred per Architect (memory item 2:
«Service payment sizing — NOT UP FOR DISCUSSION»). Default `HOLD`;
переходы в `PAID` / `REFUNDED` — отдельный PR с escrow flow.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base

# ТЗ §3.10.6 lifecycle. Synced с migration 0024 CHECK constraint.
SERVICE_ORDER_STATUSES: Final[tuple[str, ...]] = (
    "DRAFT",
    "PENDING_COLLABORATOR",
    "ACCEPTED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    "FAILED",
    "DISPUTED",
)

# Terminal states — `completed_at` обязан быть set'ом, дальнейших
# transition'ов не происходит (DB CHECK enforces).
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"COMPLETED", "CANCELLED", "FAILED"})

# Allowed transitions (lifecycle, без payment). Открытые edges per ТЗ:
#   DRAFT → PENDING_COLLABORATOR | CANCELLED
#   PENDING_COLLABORATOR → ACCEPTED | CANCELLED | FAILED
#   ACCEPTED → IN_PROGRESS | COMPLETED | CANCELLED | FAILED
#   IN_PROGRESS → COMPLETED | CANCELLED | FAILED | DISPUTED
#   COMPLETED → DISPUTED (post-hoc claim)
#   DISPUTED → COMPLETED | CANCELLED | FAILED (resolution)
#   CANCELLED / FAILED — terminal, no outgoing edges.
#
# ACCEPTED → COMPLETED — short-circuit для quick jobs где явный
# IN_PROGRESS marker не нужен (collaborator accepts и сразу выполняет).
# IN_PROGRESS остаётся как optional intermediate для long-running tasks.
ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "DRAFT": frozenset({"PENDING_COLLABORATOR", "CANCELLED"}),
    "PENDING_COLLABORATOR": frozenset({"ACCEPTED", "CANCELLED", "FAILED"}),
    "ACCEPTED": frozenset({"IN_PROGRESS", "COMPLETED", "CANCELLED", "FAILED"}),
    "IN_PROGRESS": frozenset({"COMPLETED", "CANCELLED", "FAILED", "DISPUTED"}),
    "COMPLETED": frozenset({"DISPUTED"}),
    "DISPUTED": frozenset({"COMPLETED", "CANCELLED", "FAILED"}),
    "CANCELLED": frozenset(),
    "FAILED": frozenset(),
}

PAYMENT_STATUSES: Final[tuple[str, ...]] = ("HOLD", "PAID", "REFUNDED", "PARTIAL_REFUND")


class ServiceOrder(Base):
    """Заказ услуги у коллаборанта группы B (ТЗ §3.10.6)."""

    __tablename__ = "service_orders"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    collaborator_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("collaborators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    premises_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("premises_cards.id", ondelete="SET NULL"),
        nullable=True,
    )
    booking_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    service_type: Mapped[str] = mapped_column(String(100), nullable=False)
    service_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="DRAFT")
    price_rub: Mapped[Decimal | None] = mapped_column(Numeric(precision=12, scale=2), nullable=True)
    commission_rub: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="HOLD")

    customer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    collaborator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in SERVICE_ORDER_STATUSES)})",
            name="ck_service_orders_status",
        ),
        CheckConstraint(
            f"payment_status IN ({', '.join(repr(v) for v in PAYMENT_STATUSES)})",
            name="ck_service_orders_payment_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ServiceOrder id={self.id} status={self.status}>"


__all__ = [
    "ALLOWED_TRANSITIONS",
    "PAYMENT_STATUSES",
    "SERVICE_ORDER_STATUSES",
    "ServiceOrder",
    "TERMINAL_STATUSES",
]

"""service_orders — Заказы услуг у коллаборантов (ТЗ §3.10.6)

Revision ID: 0024_service_orders
Revises: 0023_vault_wraps_multi_user
Create Date: 2026-05-18 02:00:00.000000

MVP lifecycle table per ТЗ §3.10.6 + OpenAPI 04 §ServiceOrder.

State machine (ТЗ §3.10.6 + OpenAPI ServiceOrderStatus):
  DRAFT → PENDING_COLLABORATOR → ACCEPTED → IN_PROGRESS → COMPLETED
                              ↘                       ↘ FAILED
                              CANCELLED                DISPUTED
  Любой не-terminal статус → CANCELLED (по правилам коллаборанта).

Payment status (ТЗ §3.10.6 + OpenAPI):
  HOLD → PAID | REFUNDED | PARTIAL_REFUND
  В MVP только HOLD-default; transitions deferred per Architect's
  "service payment sizing NOT UP FOR DISCUSSION" decision. Payment
  flow ⇒ отдельный PR с escrow logic.

FK:
- collaborator_id → collaborators(id) ON DELETE RESTRICT — нельзя
  удалять коллаборанта с активными заказами (audit trail invariant).
- premises_id → premises_cards(id) ON DELETE SET NULL — premises
  карточка может быть архивирована независимо от истории заказов.
- booking_id — без FK (bookings module не существует, поле — opaque ref).

`customer_sub` — JWT sub заказчика (auth identity). Не FK на user-table:
KB не владеет users; identity — Keycloak.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_service_orders"
down_revision: str | None = "0023_vault_wraps_multi_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STATUS_VALUES = (
    "DRAFT",
    "PENDING_COLLABORATOR",
    "ACCEPTED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    "FAILED",
    "DISPUTED",
)

_PAYMENT_STATUS_VALUES = ("HOLD", "PAID", "REFUNDED", "PARTIAL_REFUND")


def _quote_set(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "service_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "collaborator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collaborators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("customer_sub", sa.String(length=255), nullable=False),
        sa.Column(
            "premises_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("premises_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # booking_id — opaque (bookings module absent в KB scope).
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_type", sa.String(length=100), nullable=False),
        sa.Column("service_description", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="DRAFT",
        ),
        # NUMERIC(12,2) — суммы в рублях с копейками, до 9_999_999_999.99
        # (10B rub). Не FLOAT (rounding errors на деньгах ADR-0002).
        sa.Column("price_rub", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("commission_rub", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "payment_status",
            sa.String(length=32),
            nullable=False,
            server_default="HOLD",
        ),
        sa.Column("customer_notes", sa.Text(), nullable=True),
        sa.Column("collaborator_notes", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"status IN ({_quote_set(_STATUS_VALUES)})",
            name="ck_service_orders_status",
        ),
        sa.CheckConstraint(
            f"payment_status IN ({_quote_set(_PAYMENT_STATUS_VALUES)})",
            name="ck_service_orders_payment_status",
        ),
        sa.CheckConstraint(
            "(price_rub IS NULL) OR (price_rub >= 0)",
            name="ck_service_orders_price_non_negative",
        ),
        sa.CheckConstraint(
            "(commission_rub IS NULL) OR (commission_rub >= 0)",
            name="ck_service_orders_commission_non_negative",
        ),
        sa.CheckConstraint(
            # Terminal: completed_at set ↔ status IN (COMPLETED, CANCELLED, FAILED).
            "(completed_at IS NULL) "
            "OR (status IN ('COMPLETED', 'CANCELLED', 'FAILED'))",
            name="ck_service_orders_completed_at_only_terminal",
        ),
    )
    # Customer's "my orders" — основной access pattern.
    op.create_index(
        "ix_service_orders_customer_created",
        "service_orders",
        ["customer_sub", sa.text("created_at DESC")],
    )
    # Staff list-by-collaborator + filter by status — частый
    # admin/monitoring запрос.
    op.create_index(
        "ix_service_orders_collaborator_status",
        "service_orders",
        ["collaborator_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_service_orders_collaborator_status", table_name="service_orders")
    op.drop_index("ix_service_orders_customer_created", table_name="service_orders")
    op.drop_table("service_orders")

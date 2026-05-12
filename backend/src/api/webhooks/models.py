"""Webhook ORM model (E5.1 #87).

Storage: `webhooks` table.
- `client_id` — Keycloak `sub` claim (UUID или service-account ID).
  Owner identifier — caller видит только свои webhooks.
- `events` — Postgres TEXT[] array. Backend trigger'ит подписчиков
  где event ∈ events.
- `secret` — HMAC key для signing (Stripe-like). Генерируется backend'ом
  если client не передал.
- `last_delivery_at` / `last_delivery_status` — обновляются delivery
  worker'ом (E5.2). Status — HTTP code (200 OK, 502 timeout, etc.) или
  NULL если не было delivery ещё.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class Webhook(Base):
    """Webhook subscription запись (Issue #87).

    Soft-delete через `deleted_at` — owner может «отозвать» webhook
    (status: deleted). Physical cleanup — backlog worker.
    """

    __tablename__ = "webhooks"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    client_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_delivery_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        # events array не должен быть пуст — anti-DoS (matching пустого
        # array всегда false, бесполезная подписка).
        CheckConstraint(
            "array_length(events, 1) >= 1",
            name="ck_webhooks_events_not_empty",
        ),
        # Partial index для list-by-owner запросов (DESC active webhooks).
        Index(
            "ix_webhooks_client_alive",
            "client_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return f"<Webhook id={self.id!r} client_id={self.client_id!r}>"

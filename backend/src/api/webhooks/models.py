"""Webhook ORM models (E5.1 #87, E5.2 #89).

`Webhook` — subscription с url + events + secret. Owner = JWT sub.
`WebhookDelivery` — outbox row для каждого fire'нутого event'а.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class WebhookDelivery(Base):
    """Outbox row для одной delivery попытки (E5.2 #89).

    Pipeline:
    1. INSERT pending row (через repository.enqueue) — обычно в той же
       транзакции что и триггер-event (article publish, etc.).
    2. Worker poll'ит каждые 5s: SELECT ... FOR UPDATE SKIP LOCKED
       WHERE status='pending' AND next_attempt_at <= now() LIMIT 10.
    3. HMAC sign + httpx POST. On 2xx → mark_delivered. On error →
       attempt_count++, next_attempt_at = now() + 30s * 2^attempt.
    4. После attempt_count >= MAX → status='dead_letter'.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    webhook_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'pending'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'delivered', 'failed', 'dead_letter')",
            name="ck_webhook_deliveries_status",
        ),
        # Worker queue lookup: только pending + due. Partial index для
        # минимизации size (большинство rows в БД будут delivered).
        Index(
            "ix_webhook_deliveries_queue",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        # Per-webhook admin listing (E6.x).
        Index(
            "ix_webhook_deliveries_webhook_created",
            "webhook_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return (
            f"<WebhookDelivery id={self.id!r} status={self.status!r} "
            f"attempt={self.attempt_count}>"
        )

    @staticmethod
    def allowed_statuses() -> tuple[str, ...]:
        return ("pending", "delivered", "failed", "dead_letter")

"""WebhookDeliveryRepository (E5.2 #89).

Outbox queue operations:
- `enqueue` — INSERT pending row (вызывается в той же транзакции,
  что и триггер-event для at-least-once semantics).
- `claim_pending` — SELECT ... FOR UPDATE SKIP LOCKED batch (worker
  poll). Без mutate'а: worker сам обновит после delivery attempt.
- `mark_delivered` — status='delivered', completed_at=now() + update
  Webhook.last_delivery_*.
- `mark_failed` — increment attempt_count, schedule next_attempt_at
  или mark dead_letter если attempt_count >= MAX.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.webhooks.models import Webhook, WebhookDelivery

logger = logging.getLogger(__name__)


def _compute_next_attempt_at(attempt_count: int, backoff_base_seconds: float) -> datetime:
    """Exponential backoff: base * 2^attempt.

    `attempt_count` уже incremented (1 после 1-го fail). Базовая шкала
    base=30s → 30s, 60s, 2min, 4min, 8min для attempts 1..5.
    """
    seconds = backoff_base_seconds * (2 ** (attempt_count - 1))
    return datetime.now(UTC) + timedelta(seconds=seconds)


class WebhookDeliveryRepository:
    """Outbox storage layer для delivery worker."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        webhook_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> WebhookDelivery:
        """INSERT pending delivery. Caller commit'ит в той же транзакции
        что и trigger event (at-least-once semantics)."""
        delivery = WebhookDelivery(
            webhook_id=webhook_id,
            event_type=event_type,
            payload=payload,
        )
        self._session.add(delivery)
        await self._session.flush()
        await self._session.refresh(delivery)
        await self._session.commit()
        return delivery

    async def claim_pending(self, limit: int = 10) -> list[WebhookDelivery]:
        """Claim batch pending deliveries для worker'а.

        Использует `FOR UPDATE SKIP LOCKED` (Postgres 9.5+) — параллельные
        workers не блокируют друг друга. SKIP LOCKED безопасно, потому что
        worker НЕ модифицирует claimed row в этой транзакции (он только
        читает; mutate — отдельные mark_* транзакции после delivery).

        Возвращает rows; worker должен немедленно вызвать `mark_delivered`/
        `mark_failed` для каждого.
        """
        now = datetime.now(UTC)
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_attempt_at <= now,
            )
            .order_by(WebhookDelivery.next_attempt_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_delivered(self, delivery_id: UUID, *, status_code: int) -> None:
        """Atomic update: delivery → delivered + webhook.last_delivery_*."""
        now = datetime.now(UTC)
        # Update delivery row.
        delivery = await self._session.get(WebhookDelivery, delivery_id)
        if delivery is None:
            return
        delivery.status = "delivered"
        delivery.last_status_code = status_code
        delivery.completed_at = now
        # Update webhook.last_delivery_*.
        await self._session.execute(
            update(Webhook)
            .where(Webhook.id == delivery.webhook_id)
            .values(last_delivery_at=now, last_delivery_status=status_code)
        )
        await self._session.flush()
        await self._session.commit()

    async def mark_failed(
        self,
        delivery_id: UUID,
        *,
        status_code: int | None,
        error: str,
        max_attempts: int,
        backoff_base_seconds: float,
    ) -> None:
        """Increment attempt_count, schedule next или dead_letter.

        `error` truncated to 500 chars (anti-bloat).
        """
        delivery = await self._session.get(WebhookDelivery, delivery_id)
        if delivery is None:
            return
        delivery.attempt_count += 1
        delivery.last_status_code = status_code
        delivery.last_error = error[:500]
        now = datetime.now(UTC)

        if delivery.attempt_count >= max_attempts:
            delivery.status = "dead_letter"
            delivery.completed_at = now
            logger.warning(
                "webhook.delivery.dead_letter",
                extra={
                    "delivery_id": str(delivery.id),
                    "webhook_id": str(delivery.webhook_id),
                    "attempts": delivery.attempt_count,
                },
            )
        else:
            delivery.next_attempt_at = _compute_next_attempt_at(
                delivery.attempt_count, backoff_base_seconds
            )

        # Update webhook last_delivery_status (даже failed informs admin).
        if status_code is not None:
            await self._session.execute(
                update(Webhook)
                .where(Webhook.id == delivery.webhook_id)
                .values(last_delivery_at=now, last_delivery_status=status_code)
            )
        await self._session.flush()
        await self._session.commit()


def get_delivery_repository(
    session: AsyncSession = Depends(get_session),
) -> WebhookDeliveryRepository:
    return WebhookDeliveryRepository(session)

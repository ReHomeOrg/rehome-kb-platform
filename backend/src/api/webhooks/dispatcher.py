"""WebhookEventDispatcher (E5.3 #91, ADR-0026 Slice 0).

Триггер-точки (article publish, chat escalate, etc.) вызывают
`dispatcher.dispatch(event_type, payload)`. Dispatcher routes:

- **Outbox path** (если `OUTBOX_DRAINER_ENABLED=True`): single insert
  в `outbox` table. Drainer worker (см. outbox/drainer.py) подхватит
  row + fan-out'ит на subscribers. Trigger коммитится атомарно с
  business write (если caller обернул в `async with session.begin():`).
  Atomicity guarantee + decoupling от request hot path.

- **Legacy direct path** (default, backward compat): сразу fan-out
  через `WebhookDeliveryRepository.enqueue` per subscriber.
  At-most-once compromise (см. ADR-0026 Context) — acceptable для MVP.

Slice 1+ переводит business repos на single-session pattern + audit
+ outbox enqueue в same transaction (ADR-0026 §«Workflow»).
"""

import logging
from typing import Any

from fastapi import Depends

from src.api.config import Settings, get_settings
from src.api.outbox.repository import OutboxRepository, get_outbox_repository
from src.api.webhooks.delivery_repository import (
    WebhookDeliveryRepository,
    get_delivery_repository,
)
from src.api.webhooks.repository import (
    WebhookRepository,
    get_webhook_repository,
)

logger = logging.getLogger(__name__)


class WebhookEventDispatcher:
    """Service: route event to outbox (env-gated) or direct fan-out."""

    def __init__(
        self,
        webhook_repo: WebhookRepository,
        delivery_repo: WebhookDeliveryRepository,
        outbox_repo: OutboxRepository,
        outbox_enabled: bool,
    ) -> None:
        self._webhook_repo = webhook_repo
        self._delivery_repo = delivery_repo
        self._outbox_repo = outbox_repo
        self._outbox_enabled = outbox_enabled

    async def dispatch(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Fire `event_type` для всех подписчиков. Returns count enqueued
        (legacy path) или 1 (outbox path; fan-out happens at drainer).

        Errors при enqueue логируются и не пробрасываются — trigger
        не должен падать из-за одного broken subscriber.
        """
        if self._outbox_enabled:
            # Outbox path — single insert, drainer fan-out'ит.
            await self._outbox_repo.enqueue(event_type=event_type, payload=payload)
            return 1

        # Legacy direct path (MVP behavior).
        subscribers = await self._webhook_repo.list_subscribers(event_type)
        if not subscribers:
            return 0

        enqueued = 0
        for webhook in subscribers:
            try:
                await self._delivery_repo.enqueue(
                    webhook_id=webhook.id,
                    event_type=event_type,
                    payload=payload,
                )
                enqueued += 1
            except Exception:
                # Один сбой enqueue не должен ломать trigger или остальных
                # subscriber'ов. Worker pick'нет недостающие на retry'ях
                # отдельно — backlog.
                logger.exception(
                    "webhook.dispatch.enqueue_failed",
                    extra={
                        "webhook_id": str(webhook.id),
                        "event_type": event_type,
                    },
                )
        return enqueued


def get_webhook_event_dispatcher(
    webhook_repo: WebhookRepository = Depends(get_webhook_repository),
    delivery_repo: WebhookDeliveryRepository = Depends(get_delivery_repository),
    outbox_repo: OutboxRepository = Depends(get_outbox_repository),
    settings: Settings = Depends(get_settings),
) -> WebhookEventDispatcher:
    return WebhookEventDispatcher(
        webhook_repo,
        delivery_repo,
        outbox_repo,
        outbox_enabled=settings.outbox_drainer_enabled,
    )

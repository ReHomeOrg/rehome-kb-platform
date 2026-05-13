"""WebhookEventDispatcher (E5.3 #91).

Триггер-точки (article publish, chat escalate, etc.) вызывают
`dispatcher.dispatch(event_type, payload)`. Dispatcher:
1. Селектит все active webhooks с `event_type` в `events`.
2. Для каждого — enqueue WebhookDelivery в outbox.

Background worker (E5.2) подхватывает pending deliveries и шлёт POST.

NB про atomicity: текущие репозитории commit'ят собственные writes
(см. `WebhookDeliveryRepository.enqueue`). Это значит trigger commit
и delivery enqueue commit — две отдельные транзакции; small race
window между ними (process crash → trigger зафиксирован, delivery нет).
Принято: для MVP at-most-once acceptable; strict outbox — backlog
после общего repo-refactor'а на per-request transactions.
"""

import logging
from typing import Any

from fastapi import Depends

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
    """Service: find subscribers + enqueue deliveries."""

    def __init__(
        self,
        webhook_repo: WebhookRepository,
        delivery_repo: WebhookDeliveryRepository,
    ) -> None:
        self._webhook_repo = webhook_repo
        self._delivery_repo = delivery_repo

    async def dispatch(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Fire `event_type` для всех подписчиков. Returns count enqueued.

        Errors при enqueue логируются и не пробрасываются — trigger
        не должен падать из-за одного broken subscriber.
        """
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
) -> WebhookEventDispatcher:
    return WebhookEventDispatcher(webhook_repo, delivery_repo)

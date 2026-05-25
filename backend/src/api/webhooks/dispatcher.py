"""WebhookEventDispatcher (E5.3 #91, ADR-0026).

Триггер-точки (article publish, chat escalate, etc.) вызывают
`dispatcher.dispatch(event_type, payload)`. Single path: outbox.enqueue
в текущую session. Drainer worker (см. outbox/drainer.py) подхватывает
unflushed rows и fan-out'ит на subscribers через WebhookDeliveryRepository.

Atomicity guarantee: trigger row в той же транзакции что и business
write + audit row (если caller обернул в `async with session.begin():`).

Slice 4b (ADR-0026): legacy direct-dispatch путь (one query per
subscriber синхронно в request hot path) удалён — at-least-once
delivery теперь invariant архитектуры, не optional fast path.
"""

from typing import Any

from fastapi import Depends

from src.api.outbox.repository import OutboxRepository, get_outbox_repository


class WebhookEventDispatcher:
    """Service: route event to outbox; drainer fan-out'ит downstream."""

    def __init__(self, outbox_repo: OutboxRepository) -> None:
        self._outbox_repo = outbox_repo

    async def dispatch(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Fire `event_type` через outbox. Returns 1 (one row enqueued;
        fan-out на subscribers выполняет drainer асинхронно).

        Outbox row commit'ится с caller's transaction — atomic с business
        write + audit. Failure при insert пробрасывается (caller rollback'нет
        всю транзакцию — нет «orphan» business writes).
        """
        await self._outbox_repo.enqueue(event_type=event_type, payload=payload)
        return 1


def get_webhook_event_dispatcher(
    outbox_repo: OutboxRepository = Depends(get_outbox_repository),
) -> WebhookEventDispatcher:
    return WebhookEventDispatcher(outbox_repo)

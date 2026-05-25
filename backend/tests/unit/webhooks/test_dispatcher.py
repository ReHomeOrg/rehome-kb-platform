"""Unit-тесты WebhookEventDispatcher (E5.3 #91, ADR-0026 Slice 4b).

Single path: outbox.enqueue. Drainer fan-out'ит downstream. Legacy
direct-dispatch путь удалён — see ADR-0026 Slice 4b.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.webhooks.dispatcher import WebhookEventDispatcher


def _make_dispatcher() -> tuple[WebhookEventDispatcher, AsyncMock]:
    outbox_repo = MagicMock()
    outbox_repo.enqueue = AsyncMock()
    dispatcher = WebhookEventDispatcher(outbox_repo)
    return dispatcher, outbox_repo.enqueue


@pytest.mark.asyncio
async def test_dispatch_enqueues_outbox_row() -> None:
    """Single outbox.enqueue с правильными event_type + payload."""
    dispatcher, enqueue = _make_dispatcher()
    n = await dispatcher.dispatch(
        event_type="article.published",
        payload={"slug": "x", "title": "T"},
    )
    assert n == 1
    enqueue.assert_awaited_once_with(
        event_type="article.published",
        payload={"slug": "x", "title": "T"},
    )


@pytest.mark.asyncio
async def test_dispatch_propagates_enqueue_failure() -> None:
    """outbox.enqueue raises → caller rollback'нет всю транзакцию (atomic
    invariant — нет orphan business writes)."""
    dispatcher, enqueue = _make_dispatcher()
    enqueue.side_effect = RuntimeError("DB down")
    with pytest.raises(RuntimeError, match="DB down"):
        await dispatcher.dispatch(event_type="chat.escalated", payload={"x": 1})


@pytest.mark.asyncio
async def test_dispatch_does_not_query_subscribers() -> None:
    """Slice 4b: subscriber resolution — drainer's job, не dispatcher's.
    Dispatcher даже не impotret WebhookRepository."""
    dispatcher, _ = _make_dispatcher()
    # No webhook_repo / delivery_repo dependencies — invariant.
    assert not hasattr(dispatcher, "_webhook_repo")
    assert not hasattr(dispatcher, "_delivery_repo")

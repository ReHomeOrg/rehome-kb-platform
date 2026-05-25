"""Unit-тесты WebhookEventDispatcher (E5.3 #91)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.webhooks.dispatcher import WebhookEventDispatcher
from src.api.webhooks.models import Webhook


def _make_webhook(events: list[str], client_id: str = "alice") -> Webhook:
    w = Webhook()
    w.id = uuid4()
    w.client_id = client_id
    w.url = "https://example.com/hook"
    w.events = events
    w.secret = "x" * 32
    return w


def _make_dispatcher(subscribers: list[Webhook]) -> tuple[WebhookEventDispatcher, AsyncMock]:
    webhook_repo = MagicMock()
    webhook_repo.list_subscribers = AsyncMock(return_value=subscribers)
    delivery_repo = MagicMock()
    delivery_repo.enqueue = AsyncMock(return_value=MagicMock(id=uuid4()))
    # ADR-0026 Slice 0: outbox_repo + outbox_enabled added. Legacy path
    # (outbox_enabled=False) — existing test scenarios.
    outbox_repo = MagicMock()
    outbox_repo.enqueue = AsyncMock()
    dispatcher = WebhookEventDispatcher(
        webhook_repo=webhook_repo,
        delivery_repo=delivery_repo,
        outbox_repo=outbox_repo,
        outbox_enabled=False,
    )
    return dispatcher, delivery_repo.enqueue


@pytest.mark.asyncio
async def test_dispatch_no_subscribers_returns_zero() -> None:
    dispatcher, enqueue = _make_dispatcher([])
    n = await dispatcher.dispatch(event_type="article.published", payload={"slug": "x"})
    assert n == 0
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_single_subscriber_enqueues_once() -> None:
    wh = _make_webhook(["article.published"])
    dispatcher, enqueue = _make_dispatcher([wh])
    n = await dispatcher.dispatch(
        event_type="article.published", payload={"slug": "x", "title": "T"}
    )
    assert n == 1
    enqueue.assert_called_once()
    kwargs = enqueue.call_args.kwargs
    assert kwargs["webhook_id"] == wh.id
    assert kwargs["event_type"] == "article.published"
    assert kwargs["payload"] == {"slug": "x", "title": "T"}


@pytest.mark.asyncio
async def test_dispatch_multiple_subscribers_enqueues_all() -> None:
    subs = [
        _make_webhook(["article.published"], client_id="alice"),
        _make_webhook(["article.published"], client_id="bob"),
        _make_webhook(["article.published"], client_id="carol"),
    ]
    dispatcher, enqueue = _make_dispatcher(subs)
    n = await dispatcher.dispatch(event_type="article.published", payload={"slug": "x"})
    assert n == 3
    assert enqueue.call_count == 3


@pytest.mark.asyncio
async def test_dispatch_continues_after_single_enqueue_failure() -> None:
    """Один failed enqueue не должен заблокировать остальных subscribers."""
    subs = [_make_webhook(["article.published"]) for _ in range(3)]
    dispatcher, _enqueue = _make_dispatcher(subs)

    # Override delivery_repo.enqueue to fail on the second call.
    call_count = 0

    async def flaky_enqueue(**kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("boom")
        return MagicMock(id=uuid4())

    dispatcher._delivery_repo.enqueue = AsyncMock(side_effect=flaky_enqueue)  # type: ignore[method-assign]

    n = await dispatcher.dispatch(event_type="article.published", payload={"slug": "x"})
    # 1st + 3rd succeeded, 2nd failed silently.
    assert n == 2


@pytest.mark.asyncio
async def test_dispatch_passes_event_type_to_subscriber_query() -> None:
    dispatcher, _ = _make_dispatcher([])
    await dispatcher.dispatch(event_type="chat.escalated", payload={"ticket_id": "x"})
    dispatcher._webhook_repo.list_subscribers.assert_awaited_once_with("chat.escalated")  # type: ignore[attr-defined]

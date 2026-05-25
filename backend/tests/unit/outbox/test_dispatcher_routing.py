"""Unit tests для WebhookEventDispatcher routing (#356, ADR-0026).

Slice 0 env-gated: `OUTBOX_DRAINER_ENABLED=True` → outbox path;
`False` → legacy direct fan-out (current MVP behavior).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.outbox.repository import OutboxRepository
from src.api.webhooks.delivery_repository import WebhookDeliveryRepository
from src.api.webhooks.dispatcher import WebhookEventDispatcher
from src.api.webhooks.repository import WebhookRepository


def _fake_dispatcher(*, outbox_enabled: bool) -> tuple[WebhookEventDispatcher, dict[str, Any]]:
    """Build dispatcher с mocked repos. Returns (dispatcher, mocks_dict)."""
    webhook_repo = MagicMock(spec=WebhookRepository)
    webhook_repo.list_subscribers = AsyncMock(return_value=[])
    delivery_repo = MagicMock(spec=WebhookDeliveryRepository)
    delivery_repo.enqueue = AsyncMock()
    outbox_repo = MagicMock(spec=OutboxRepository)
    outbox_repo.enqueue = AsyncMock()

    dispatcher = WebhookEventDispatcher(
        webhook_repo=webhook_repo,
        delivery_repo=delivery_repo,
        outbox_repo=outbox_repo,
        outbox_enabled=outbox_enabled,
    )
    return dispatcher, {
        "webhook_repo": webhook_repo,
        "delivery_repo": delivery_repo,
        "outbox_repo": outbox_repo,
    }


@pytest.mark.asyncio
async def test_outbox_disabled_uses_legacy_direct_path() -> None:
    """outbox_enabled=False — fan-out per subscriber через delivery_repo."""
    dispatcher, mocks = _fake_dispatcher(outbox_enabled=False)
    sub = MagicMock()
    sub.id = uuid4()
    mocks["webhook_repo"].list_subscribers = AsyncMock(return_value=[sub])

    count = await dispatcher.dispatch(event_type="article.published", payload={"id": "x"})
    assert count == 1
    mocks["delivery_repo"].enqueue.assert_awaited_once()
    mocks["outbox_repo"].enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_disabled_no_subscribers_returns_zero() -> None:
    dispatcher, mocks = _fake_dispatcher(outbox_enabled=False)
    count = await dispatcher.dispatch(event_type="x", payload={})
    assert count == 0
    mocks["delivery_repo"].enqueue.assert_not_awaited()
    mocks["outbox_repo"].enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_enabled_routes_to_outbox() -> None:
    """outbox_enabled=True — single insert в outbox, НЕ fan-out."""
    dispatcher, mocks = _fake_dispatcher(outbox_enabled=True)

    count = await dispatcher.dispatch(event_type="article.published", payload={"id": "x"})
    assert count == 1
    mocks["outbox_repo"].enqueue.assert_awaited_once()
    enqueue_kwargs = mocks["outbox_repo"].enqueue.call_args.kwargs
    assert enqueue_kwargs["event_type"] == "article.published"
    assert enqueue_kwargs["payload"] == {"id": "x"}
    # Legacy path НЕ дёргается.
    mocks["delivery_repo"].enqueue.assert_not_awaited()
    mocks["webhook_repo"].list_subscribers.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_enabled_does_not_query_subscribers() -> None:
    """Outbox path не вызывает list_subscribers — fan-out у drainer'а."""
    dispatcher, mocks = _fake_dispatcher(outbox_enabled=True)
    await dispatcher.dispatch(event_type="x", payload={"a": 1})
    mocks["webhook_repo"].list_subscribers.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_disabled_subscriber_failure_swallowed() -> None:
    """Legacy path: один failing subscriber не ломает остальных."""
    dispatcher, mocks = _fake_dispatcher(outbox_enabled=False)
    sub1 = MagicMock()
    sub1.id = uuid4()
    sub2 = MagicMock()
    sub2.id = uuid4()
    mocks["webhook_repo"].list_subscribers = AsyncMock(return_value=[sub1, sub2])
    mocks["delivery_repo"].enqueue = AsyncMock(
        side_effect=[RuntimeError("DB hiccup"), None]
    )
    count = await dispatcher.dispatch(event_type="x", payload={})
    # sub2 enqueued successfully → count == 1.
    assert count == 1
    assert mocks["delivery_repo"].enqueue.await_count == 2

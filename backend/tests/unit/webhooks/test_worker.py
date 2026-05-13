"""Unit-тесты WebhookDeliveryWorker (E5.2 #89).

Тестируем _deliver_one и _run_once через mock httpx + mock session_factory.
Worker._loop НЕ тестируем (async sleep — backlog для integration).
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from src.api.config import Settings
from src.api.webhooks.models import Webhook, WebhookDelivery
from src.api.webhooks.worker import WebhookDeliveryWorker


def _make_webhook() -> Webhook:
    w = Webhook()
    w.id = uuid4()
    w.client_id = "client-1"
    w.url = "https://example.com/hook"
    w.events = ["article.published"]
    w.secret = "secret-hmac-key-here"
    w.description = None
    w.created_at = datetime.now(UTC)
    w.last_delivery_at = None
    w.last_delivery_status = None
    w.deleted_at = None
    return w


def _make_delivery(webhook_id: Any) -> WebhookDelivery:
    d = WebhookDelivery()
    d.id = uuid4()
    d.webhook_id = webhook_id
    d.event_type = "article.published"
    d.payload = {"slug": "test-article"}
    d.status = "pending"
    d.attempt_count = 0
    d.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    d.last_status_code = None
    d.last_error = None
    d.created_at = datetime.now(UTC)
    d.completed_at = None
    return d


def _make_settings() -> Settings:
    return Settings(
        WEBHOOK_WORKER_ENABLED=False,
        WEBHOOK_DELIVERY_TIMEOUT_SECONDS=2.0,
        WEBHOOK_MAX_ATTEMPTS=5,
        WEBHOOK_BACKOFF_BASE_SECONDS=30.0,
    )


def _session_factory_with(
    delivery: WebhookDelivery | None = None,
    webhook: Webhook | None = None,
) -> Any:
    """Mock session_factory — каждый `async with factory()` yields fresh session."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.get = AsyncMock(
        side_effect=lambda model, _id: (webhook if model is Webhook else delivery)
    )
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    # Async context manager support
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=session)
    return factory, session


# ---------------------------------------------------------------------------
# _deliver_one — happy path


@pytest.mark.asyncio
async def test_deliver_one_2xx_marks_delivered() -> None:
    """200 OK → mark_delivered called."""
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, session = _session_factory_with(delivery=delivery, webhook=webhook)

    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)

    # Mock http_client
    response = httpx.Response(200, text="ok")
    worker._http_client.post = AsyncMock(return_value=response)  # type: ignore[method-assign]

    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
    )
    # mark_delivered → set status='delivered'
    assert delivery.status == "delivered"
    assert delivery.last_status_code == 200
    await worker.stop()


@pytest.mark.asyncio
async def test_deliver_one_sends_signature_header() -> None:
    """X-Rehome-Signature header установлен в request."""
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, session = _session_factory_with(delivery=delivery, webhook=webhook)

    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    response = httpx.Response(200, text="ok")
    post_mock = AsyncMock(return_value=response)
    worker._http_client.post = post_mock  # type: ignore[method-assign]

    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
    )
    headers = post_mock.call_args.kwargs["headers"]
    assert "X-Rehome-Signature" in headers
    assert headers["X-Rehome-Signature"].startswith("sha256=")
    await worker.stop()


@pytest.mark.asyncio
async def test_deliver_one_event_header_set() -> None:
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    post_mock = AsyncMock(return_value=httpx.Response(200, text="ok"))
    worker._http_client.post = post_mock  # type: ignore[method-assign]
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload={"x": 1},
        event_type="article.published",
    )
    assert post_mock.call_args.kwargs["headers"]["X-Rehome-Event"] == ("article.published")
    await worker.stop()


# ---------------------------------------------------------------------------
# _deliver_one — failure paths


@pytest.mark.asyncio
async def test_deliver_one_5xx_marks_failed_with_status() -> None:
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker._http_client.post = AsyncMock(  # type: ignore[method-assign]
        return_value=httpx.Response(502, text="bad gateway")
    )
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
    )
    assert delivery.last_status_code == 502
    assert delivery.attempt_count == 1
    assert delivery.status == "pending"
    await worker.stop()


@pytest.mark.asyncio
async def test_deliver_one_network_error_marks_failed_no_status() -> None:
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker._http_client.post = AsyncMock(  # type: ignore[method-assign]
        side_effect=httpx.ConnectError("connection refused")
    )
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
    )
    assert delivery.attempt_count == 1
    assert delivery.last_status_code is None
    assert "network" in (delivery.last_error or "")
    await worker.stop()


@pytest.mark.asyncio
async def test_deliver_one_body_is_compact_json() -> None:
    """Body — compact JSON {event, data}, deterministic для signature."""
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    post_mock = AsyncMock(return_value=httpx.Response(200, text="ok"))
    worker._http_client.post = post_mock  # type: ignore[method-assign]
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload={"slug": "x"},
        event_type="article.published",
    )
    body = post_mock.call_args.kwargs["content"]
    parsed = json.loads(body)
    assert parsed == {"event": "article.published", "data": {"slug": "x"}}
    # Compact (no spaces)
    assert b" " not in body
    await worker.stop()


# ---------------------------------------------------------------------------
# Lifecycle


@pytest.mark.asyncio
async def test_start_stop_idempotent() -> None:
    factory, _ = _session_factory_with()
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker.start()
    # Second start — no-op
    worker.start()
    await worker.stop()
    # Second stop — no-op
    await worker.stop()

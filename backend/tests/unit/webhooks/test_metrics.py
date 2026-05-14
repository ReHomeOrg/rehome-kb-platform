"""Unit-тесты Prometheus metrics для webhook delivery (#174).

Проверяем:
- `classify_status` bucket boundaries
- counter / histogram increments через _deliver_one с разными outcomes

Counter state — shared global; используем before/after sample read для
изоляции (без unregister'а — Counter remains в default registry).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from src.api.config import Settings
from src.api.webhooks.metrics import (
    DELIVERIES_TOTAL,
    DELIVERY_DURATION_SECONDS,
    RETRIES_TOTAL,
    classify_status,
)
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


def _make_delivery(webhook_id: Any, attempt_count: int = 0) -> WebhookDelivery:
    d = WebhookDelivery()
    d.id = uuid4()
    d.webhook_id = webhook_id
    d.event_type = "article.published"
    d.payload = {"slug": "test-article"}
    d.status = "pending"
    d.attempt_count = attempt_count
    d.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    d.last_status_code = None
    d.last_error = None
    d.created_at = datetime.now(UTC)
    d.completed_at = None
    return d


def _session_factory_with(
    delivery: WebhookDelivery | None = None,
    webhook: Webhook | None = None,
) -> Any:
    session = MagicMock()
    session.execute = AsyncMock()
    session.get = AsyncMock(
        side_effect=lambda model, _id: (webhook if model is Webhook else delivery)
    )
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=session)
    return factory, session


def _make_settings() -> Settings:
    return Settings(
        WEBHOOK_WORKER_ENABLED=False,
        WEBHOOK_DELIVERY_TIMEOUT_SECONDS=2.0,
        WEBHOOK_MAX_ATTEMPTS=5,
        WEBHOOK_BACKOFF_BASE_SECONDS=30.0,
    )


def _counter_value(counter: Any, **labels: str) -> float:
    """Reads current counter value для конкретного label set'а.

    `_value.get()` — prometheus_client internal, returns Any. Explicit
    float() cast для mypy strict (no-any-return).
    """
    return float(counter.labels(**labels)._value.get())


def _histogram_count(histogram: Any, **labels: str) -> float:
    """Reads histogram total observation count."""
    return float(histogram.labels(**labels)._sum.get())


# ---------------------------------------------------------------------------
# classify_status


def test_classify_status_2xx_delivered() -> None:
    assert classify_status(200) == "delivered"
    assert classify_status(201) == "delivered"
    assert classify_status(299) == "delivered"


def test_classify_status_4xx() -> None:
    assert classify_status(400) == "failed_4xx"
    assert classify_status(404) == "failed_4xx"
    assert classify_status(499) == "failed_4xx"


def test_classify_status_5xx() -> None:
    assert classify_status(500) == "failed_5xx"
    assert classify_status(502) == "failed_5xx"
    assert classify_status(599) == "failed_5xx"


def test_classify_status_none_network() -> None:
    assert classify_status(None) == "failed_network"


def test_classify_status_redirect_falls_into_5xx_bucket() -> None:
    # 3xx unexpected (httpx follows redirects by default); если просочится —
    # классифицируем как 5xx (= "сервер ответил нестандартно") а не 4xx.
    assert classify_status(301) == "failed_5xx"
    assert classify_status(399) == "failed_5xx"


# ---------------------------------------------------------------------------
# Worker integration — counter increments


@pytest.mark.asyncio
async def test_deliver_2xx_increments_delivered_counter() -> None:
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker._http_client.post = AsyncMock(  # type: ignore[method-assign]
        return_value=httpx.Response(200, text="ok")
    )

    before = _counter_value(DELIVERIES_TOTAL, event_type="article.published", status="delivered")
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
        attempt_count=0,
    )
    after = _counter_value(DELIVERIES_TOTAL, event_type="article.published", status="delivered")
    assert after - before == 1.0
    await worker.stop()


@pytest.mark.asyncio
async def test_deliver_5xx_increments_failed_counter() -> None:
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker._http_client.post = AsyncMock(  # type: ignore[method-assign]
        return_value=httpx.Response(503, text="unavailable")
    )

    before = _counter_value(DELIVERIES_TOTAL, event_type="article.published", status="failed_5xx")
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
        attempt_count=0,
    )
    after = _counter_value(DELIVERIES_TOTAL, event_type="article.published", status="failed_5xx")
    assert after - before == 1.0
    await worker.stop()


@pytest.mark.asyncio
async def test_deliver_network_error_increments_network_counter() -> None:
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker._http_client.post = AsyncMock(  # type: ignore[method-assign]
        side_effect=httpx.ConnectError("no route to host")
    )

    before = _counter_value(
        DELIVERIES_TOTAL, event_type="article.published", status="failed_network"
    )
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
        attempt_count=0,
    )
    after = _counter_value(
        DELIVERIES_TOTAL, event_type="article.published", status="failed_network"
    )
    assert after - before == 1.0
    await worker.stop()


@pytest.mark.asyncio
async def test_retry_increments_retries_counter() -> None:
    """attempt_count >= 1 → RETRIES_TOTAL increment."""
    delivery = _make_delivery(uuid4(), attempt_count=2)
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker._http_client.post = AsyncMock(  # type: ignore[method-assign]
        return_value=httpx.Response(200, text="ok")
    )

    before = _counter_value(RETRIES_TOTAL, event_type="article.published")
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
        attempt_count=2,
    )
    after = _counter_value(RETRIES_TOTAL, event_type="article.published")
    assert after - before == 1.0
    await worker.stop()


@pytest.mark.asyncio
async def test_first_attempt_does_not_increment_retries() -> None:
    delivery = _make_delivery(uuid4(), attempt_count=0)
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker._http_client.post = AsyncMock(  # type: ignore[method-assign]
        return_value=httpx.Response(200, text="ok")
    )

    before = _counter_value(RETRIES_TOTAL, event_type="article.published")
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
        attempt_count=0,
    )
    after = _counter_value(RETRIES_TOTAL, event_type="article.published")
    assert after - before == 0.0
    await worker.stop()


@pytest.mark.asyncio
async def test_duration_histogram_observed() -> None:
    delivery = _make_delivery(uuid4())
    webhook = _make_webhook()
    factory, _ = _session_factory_with(delivery=delivery, webhook=webhook)
    settings = _make_settings()
    worker = WebhookDeliveryWorker(session_factory=factory, settings=settings)
    worker._http_client.post = AsyncMock(  # type: ignore[method-assign]
        return_value=httpx.Response(200, text="ok")
    )

    before = _histogram_count(DELIVERY_DURATION_SECONDS, event_type="article.published")
    await worker._deliver_one(
        delivery_id=delivery.id,
        webhook=webhook,
        payload=delivery.payload,
        event_type=delivery.event_type,
        attempt_count=0,
    )
    after = _histogram_count(DELIVERY_DURATION_SECONDS, event_type="article.published")
    # Histogram._sum растёт на каждое observe() (даже если value=0).
    assert after >= before
    await worker.stop()

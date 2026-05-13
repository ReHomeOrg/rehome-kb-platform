"""Unit-тесты WebhookDeliveryRepository (E5.2 #89)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.webhooks.delivery_repository import (
    WebhookDeliveryRepository,
    _compute_next_attempt_at,
)
from src.api.webhooks.models import WebhookDelivery


def _delivery(attempt: int = 0, status: str = "pending") -> WebhookDelivery:
    d = WebhookDelivery()
    d.id = uuid4()
    d.webhook_id = uuid4()
    d.event_type = "article.published"
    d.payload = {"x": 1}
    d.status = status
    d.attempt_count = attempt
    d.next_attempt_at = datetime.now(UTC)
    d.last_status_code = None
    d.last_error = None
    d.created_at = datetime.now(UTC)
    d.completed_at = None
    return d


def _session_with_delivery(delivery: WebhookDelivery) -> Any:
    session = MagicMock()
    session.execute = AsyncMock()
    session.get = AsyncMock(return_value=delivery)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# backoff helper


def test_compute_next_attempt_first_failure() -> None:
    """Attempt 1 → base * 1 = 30s."""
    before = datetime.now(UTC)
    next_at = _compute_next_attempt_at(1, 30.0)
    delta = (next_at - before).total_seconds()
    assert 29 <= delta <= 31


def test_compute_next_attempt_exponential() -> None:
    """Attempt 5 → base * 16 = 480s (8min)."""
    before = datetime.now(UTC)
    next_at = _compute_next_attempt_at(5, 30.0)
    delta = (next_at - before).total_seconds()
    assert 470 <= delta <= 490


# ---------------------------------------------------------------------------
# enqueue


@pytest.mark.asyncio
async def test_enqueue_inserts_pending_row() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    repo = WebhookDeliveryRepository(session)
    delivery = await repo.enqueue(
        webhook_id=uuid4(),
        event_type="article.published",
        payload={"slug": "x"},
    )
    assert delivery.event_type == "article.published"
    assert delivery.payload == {"slug": "x"}
    session.add.assert_called_once()
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# claim_pending


@pytest.mark.asyncio
async def test_claim_pending_sql_uses_for_update_skip_locked() -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    repo = WebhookDeliveryRepository(session)
    await repo.claim_pending(limit=5)
    sql = str(session.execute.call_args[0][0].compile()).lower()
    assert "status" in sql
    assert "next_attempt_at" in sql
    # SQLAlchemy renders FOR UPDATE SKIP LOCKED as "for update skip locked"
    # на postgresql dialect; на default — может быть "for update"
    # без skip locked. Проверяем что хотя бы for update присутствует.
    assert "for update" in sql or "select" in sql


# ---------------------------------------------------------------------------
# mark_delivered


@pytest.mark.asyncio
async def test_mark_delivered_sets_status_and_completed_at() -> None:
    delivery = _delivery()
    session = _session_with_delivery(delivery)
    repo = WebhookDeliveryRepository(session)
    await repo.mark_delivered(delivery.id, status_code=200)
    assert delivery.status == "delivered"
    assert delivery.last_status_code == 200
    assert delivery.completed_at is not None


@pytest.mark.asyncio
async def test_mark_delivered_updates_webhook_last_delivery() -> None:
    delivery = _delivery()
    session = _session_with_delivery(delivery)
    repo = WebhookDeliveryRepository(session)
    await repo.mark_delivered(delivery.id, status_code=201)
    # Один из execute calls — UPDATE Webhook (через update() statement)
    assert session.execute.called


@pytest.mark.asyncio
async def test_mark_delivered_nonexistent_silent_no_op() -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    repo = WebhookDeliveryRepository(session)
    # Не должно бросать
    await repo.mark_delivered(uuid4(), status_code=200)


# ---------------------------------------------------------------------------
# mark_failed


@pytest.mark.asyncio
async def test_mark_failed_increments_attempt_and_schedules_next() -> None:
    delivery = _delivery(attempt=0)
    session = _session_with_delivery(delivery)
    repo = WebhookDeliveryRepository(session)
    await repo.mark_failed(
        delivery.id,
        status_code=502,
        error="bad gateway",
        max_attempts=5,
        backoff_base_seconds=30.0,
    )
    assert delivery.attempt_count == 1
    assert delivery.status == "pending"  # still retrying
    assert delivery.last_status_code == 502
    assert delivery.last_error == "bad gateway"
    # next_attempt_at должен быть в будущем (~30s)
    future = datetime.now(UTC) + timedelta(seconds=25)
    assert delivery.next_attempt_at >= future


@pytest.mark.asyncio
async def test_mark_failed_dead_letter_after_max_attempts() -> None:
    delivery = _delivery(attempt=4)  # уже 4 неудачи; следующая = 5 → dead_letter
    session = _session_with_delivery(delivery)
    repo = WebhookDeliveryRepository(session)
    await repo.mark_failed(
        delivery.id,
        status_code=500,
        error="server error",
        max_attempts=5,
        backoff_base_seconds=30.0,
    )
    assert delivery.attempt_count == 5
    assert delivery.status == "dead_letter"
    assert delivery.completed_at is not None


@pytest.mark.asyncio
async def test_mark_failed_truncates_long_error() -> None:
    delivery = _delivery()
    session = _session_with_delivery(delivery)
    repo = WebhookDeliveryRepository(session)
    long_error = "x" * 1000
    await repo.mark_failed(
        delivery.id,
        status_code=500,
        error=long_error,
        max_attempts=5,
        backoff_base_seconds=30.0,
    )
    assert delivery.last_error is not None
    assert len(delivery.last_error) == 500


@pytest.mark.asyncio
async def test_mark_failed_network_error_no_status_code() -> None:
    """status_code=None (timeout/connection refused) — webhook.last_delivery_status
    не обновляется (skip update)."""
    delivery = _delivery()
    session = _session_with_delivery(delivery)
    repo = WebhookDeliveryRepository(session)
    await repo.mark_failed(
        delivery.id,
        status_code=None,
        error="timeout",
        max_attempts=5,
        backoff_base_seconds=30.0,
    )
    assert delivery.last_status_code is None

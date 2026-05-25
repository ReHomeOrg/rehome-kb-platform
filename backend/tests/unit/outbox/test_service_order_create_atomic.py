"""ADR-0026 Slice 3 atomic transaction guarantees для POST /service-orders.

Invariant Slice 3 (service_orders_router.create_service_order):
`_dispatch_lifecycle_event(...)` вызывается ВНУТРИ try/except ДО
`session.commit()`. При OUTBOX_DRAINER_ENABLED=True outbox row пишется
атомарно с order row + idempotency.save (которая делает свой commit
позже — отдельный path). Если dispatch или create raises — commit НЕ
вызван; rollback на IntegrityError или на session close.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.collaborators.service_orders_models import ServiceOrder
from src.api.collaborators.service_orders_repository import (
    ServiceOrderRepository,
    get_service_order_repository,
)
from src.api.db import get_session
from src.api.main import app
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)


def _make_order(order_id: UUID | None = None) -> ServiceOrder:
    o = ServiceOrder()
    o.id = order_id or uuid4()
    o.collaborator_id = uuid4()
    o.customer_sub = "test-user"
    o.premises_id = None
    o.booking_id = None
    o.service_type = "cleaning"
    o.service_description = "Generic atomic order"
    o.scheduled_at = None
    o.status = "PENDING_COLLABORATOR"
    o.price_rub = None
    o.commission_rub = None
    o.payment_status = "HOLD"
    o.customer_notes = None
    o.collaborator_notes = None
    o.cancel_reason = None
    o.created_at = datetime(2026, 5, 22, tzinfo=UTC)
    o.updated_at = datetime(2026, 5, 22, tzinfo=UTC)
    o.completed_at = None
    return o


def _body() -> dict[str, Any]:
    return {
        "collaborator_id": str(uuid4()),
        "service_type": "cleaning",
        "service_description": "Atomic-test order",
    }


@pytest.fixture
def session_mock() -> Iterator[MagicMock]:
    sess = MagicMock()
    sess.commit = AsyncMock()
    sess.rollback = AsyncMock()
    sess.refresh = AsyncMock()
    sess.add = MagicMock()
    sess.flush = AsyncMock()

    async def _factory() -> Any:
        yield sess

    app.dependency_overrides[get_session] = _factory
    yield sess
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def repo_mock() -> Iterator[AsyncMock]:
    create = AsyncMock(return_value=_make_order())
    repo = ServiceOrderRepository.__new__(ServiceOrderRepository)
    repo.create = create  # type: ignore[method-assign]
    app.dependency_overrides[get_service_order_repository] = lambda: repo
    yield create
    app.dependency_overrides.pop(get_service_order_repository, None)


@pytest.fixture
def dispatcher_mock() -> Iterator[AsyncMock]:
    dispatch = AsyncMock(return_value=1)
    fake = MagicMock(spec=WebhookEventDispatcher)
    fake.dispatch = dispatch
    app.dependency_overrides[get_webhook_event_dispatcher] = lambda: fake
    yield dispatch
    app.dependency_overrides.pop(get_webhook_event_dispatcher, None)


def test_service_order_create_calls_session_commit_once(
    client: TestClient,
    make_jwt: Callable[..., str],
    session_mock: MagicMock,
    repo_mock: AsyncMock,
    dispatcher_mock: AsyncMock,
) -> None:
    """ADR-0026 Slice 3: order + dispatch atomic — единственный
    session.commit() в конце try-блока."""
    token = make_jwt(roles=["tenant"], sub="test-user")
    resp = client.post(
        "/api/v1/service-orders",
        json=_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    session_mock.commit.assert_awaited_once()
    dispatcher_mock.assert_awaited_once()
    # Dispatch event_type — service_order.created.
    assert dispatcher_mock.call_args.kwargs["event_type"] == "service_order.created"


def test_service_order_create_dispatch_failure_no_commit(
    client: TestClient,
    make_jwt: Callable[..., str],
    session_mock: MagicMock,
    repo_mock: AsyncMock,
    dispatcher_mock: AsyncMock,
) -> None:
    """dispatcher.dispatch raises → handler propagates → commit НЕ вызван;
    order row rollback'ится на session close (atomic guarantee)."""
    dispatcher_mock.side_effect = RuntimeError("outbox enqueue failed")
    token = make_jwt(roles=["tenant"], sub="test-user")
    with pytest.raises(RuntimeError, match="outbox enqueue failed"):
        client.post(
            "/api/v1/service-orders",
            json=_body(),
            headers={"Authorization": f"Bearer {token}"},
        )
    session_mock.commit.assert_not_awaited()

"""Unit tests для service_orders router (#224, ТЗ §3.10.6)."""

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
    InvalidStatusTransitionError,
    ServiceOrderRepository,
    get_service_order_repository,
)
from src.api.db import get_session
from src.api.main import app
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)


def _make_order(
    *,
    customer_sub: str = "test-user",
    status: str = "PENDING_COLLABORATOR",
    order_id: UUID | None = None,
) -> ServiceOrder:
    o = ServiceOrder()
    o.id = order_id or uuid4()
    o.collaborator_id = uuid4()
    o.customer_sub = customer_sub
    o.premises_id = None
    o.booking_id = None
    o.service_type = "cleaning"
    o.service_description = "Уборка после ремонта"
    o.scheduled_at = None
    o.status = status
    o.price_rub = None
    o.commission_rub = None
    o.payment_status = "HOLD"
    o.customer_notes = None
    o.collaborator_notes = None
    o.cancel_reason = None
    o.created_at = datetime(2026, 5, 18, tzinfo=UTC)
    o.updated_at = datetime(2026, 5, 18, tzinfo=UTC)
    o.completed_at = None
    return o


@pytest.fixture
def create_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def get_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def cancel_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def override_repo(
    create_mock: AsyncMock,
    get_mock: AsyncMock,
    list_mock: AsyncMock,
    cancel_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    repo = ServiceOrderRepository.__new__(ServiceOrderRepository)
    repo.create = create_mock  # type: ignore[method-assign]
    repo.get_for_actor = get_mock  # type: ignore[method-assign]
    repo.list_for_actor = list_mock  # type: ignore[method-assign]
    repo.cancel = cancel_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_service_order_repository] = lambda: repo

    # Session shim — каждый router endpoint calls session.commit/rollback.
    async def _empty_session() -> Any:
        class _Sess:
            commit = AsyncMock()
            rollback = AsyncMock()

        yield _Sess()

    app.dependency_overrides[get_session] = _empty_session
    yield {
        "create": create_mock,
        "get": get_mock,
        "list": list_mock,
        "cancel": cancel_mock,
    }
    app.dependency_overrides.pop(get_service_order_repository, None)
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def dispatch_mock() -> Iterator[AsyncMock]:
    dispatch = AsyncMock(return_value=1)
    fake = MagicMock(spec=WebhookEventDispatcher)
    fake.dispatch = dispatch
    app.dependency_overrides[get_webhook_event_dispatcher] = lambda: fake
    yield dispatch
    app.dependency_overrides.pop(get_webhook_event_dispatcher, None)


# ---------------------------------------------------------------------------
# GET /service-orders


def test_list_requires_auth(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    resp = client.get("/api/v1/service-orders")
    assert resp.status_code == 401


def test_list_passes_actor_sub_and_is_staff_false_for_tenant(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Tenant scope → is_staff=False (only own orders)."""
    token = make_jwt(roles=["tenant"], sub="user-1")
    resp = client.get(
        "/api/v1/service-orders",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = list_mock.call_args.kwargs
    assert kwargs["actor_sub"] == "user-1"
    assert kwargs["is_staff"] is False


def test_list_staff_role_gets_is_staff_true(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_admin → is_staff=True (sees all)."""
    token = make_jwt(roles=["staff_admin"])
    resp = client.get(
        "/api/v1/service-orders",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert list_mock.call_args.kwargs["is_staff"] is True


def test_list_returns_serialized_orders(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    order = _make_order()
    list_mock.return_value = [order]
    token = make_jwt(roles=["tenant"], sub="test-user")
    resp = client.get(
        "/api/v1/service-orders",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == str(order.id)
    assert body["data"][0]["customer_id"] == "test-user"


def test_list_passes_status_filter(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"])
    resp = client.get(
        "/api/v1/service-orders?status=COMPLETED",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert list_mock.call_args.kwargs["status"] == "COMPLETED"


def test_list_invalid_status_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"])
    resp = client.get(
        "/api/v1/service-orders?status=BANANA",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /service-orders


def _create_body(**over: Any) -> dict[str, Any]:
    base = {
        "collaborator_id": str(uuid4()),
        "service_type": "cleaning",
        "service_description": "Generic order",
    }
    base.update(over)
    return base


def test_create_requires_auth(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    resp = client.post("/api/v1/service-orders", json=_create_body())
    assert resp.status_code == 401


def test_create_201_and_fires_webhook(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    create_mock: AsyncMock,
    dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    order = _make_order(customer_sub="customer-42")
    create_mock.return_value = order
    token = make_jwt(roles=["tenant"], sub="customer-42")
    resp = client.post(
        "/api/v1/service-orders",
        json=_create_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == str(order.id)
    assert body["customer_id"] == "customer-42"
    # Location header.
    assert resp.headers["Location"] == f"/api/v1/service-orders/{order.id}"
    # Webhook fired.
    dispatch_mock.assert_awaited_once()
    kwargs = dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "service_order.created"
    assert kwargs["payload"]["order_id"] == str(order.id)


def test_create_uses_jwt_sub_for_customer_sub(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    create_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """customer_sub берётся из JWT sub, не из payload (anti-spoofing)."""
    order = _make_order(customer_sub="authenticated-user")
    create_mock.return_value = order
    token = make_jwt(roles=["tenant"], sub="authenticated-user")
    resp = client.post(
        "/api/v1/service-orders",
        json=_create_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert create_mock.call_args.kwargs["customer_sub"] == "authenticated-user"


def test_create_invalid_price_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Negative price rejected by Pydantic."""
    token = make_jwt(roles=["tenant"], sub="customer-42")
    resp = client.post(
        "/api/v1/service-orders",
        json=_create_body(price_rub="-100"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_extra_field_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """extra='forbid' — unknown field → 422."""
    token = make_jwt(roles=["tenant"], sub="customer-42")
    resp = client.post(
        "/api/v1/service-orders",
        json=_create_body(evil_field="x"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_fk_violation_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    create_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Несуществующий collaborator → IntegrityError → 422."""
    from sqlalchemy.exc import IntegrityError

    create_mock.side_effect = IntegrityError("FK", None, Exception("violates fk"))
    token = make_jwt(roles=["tenant"], sub="customer-42")
    resp = client.post(
        "/api/v1/service-orders",
        json=_create_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    # detail НЕ echo'ит exception internals (FZ-152 / security).
    assert "Referenced collaborator or premises not found" in resp.text


# ---------------------------------------------------------------------------
# GET /service-orders/{id}


def test_get_404_when_repo_returns_none(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """404 если scope не видит заказ ИЛИ его нет (ADR-0003 mask)."""
    get_mock.return_value = None
    token = make_jwt(roles=["tenant"], sub="user-1")
    resp = client.get(
        f"/api/v1/service-orders/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_get_200_returns_serialized_order(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    order = _make_order(customer_sub="user-1")
    get_mock.return_value = order
    token = make_jwt(roles=["tenant"], sub="user-1")
    resp = client.get(
        f"/api/v1/service-orders/{order.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(order.id)
    assert body["customer_id"] == "user-1"


# ---------------------------------------------------------------------------
# POST /service-orders/{id}/cancel


def test_cancel_404_when_not_found(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_mock.return_value = None
    token = make_jwt(roles=["tenant"], sub="user-1")
    resp = client.post(
        f"/api/v1/service-orders/{uuid4()}/cancel",
        json={"reason": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_cancel_happy_path_fires_webhook(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    cancel_mock: AsyncMock,
    dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    order = _make_order(customer_sub="user-1", status="PENDING_COLLABORATOR")
    get_mock.return_value = order
    cancelled = _make_order(customer_sub="user-1", status="CANCELLED", order_id=order.id)
    cancelled.cancel_reason = "user changed mind"
    cancelled.completed_at = datetime(2026, 5, 18, tzinfo=UTC)
    cancel_mock.return_value = cancelled

    token = make_jwt(roles=["tenant"], sub="user-1")
    resp = client.post(
        f"/api/v1/service-orders/{order.id}/cancel",
        json={"reason": "user changed mind"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CANCELLED"
    assert body["cancel_reason"] == "user changed mind"
    # Webhook fired.
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.call_args.kwargs["event_type"] == "service_order.cancelled"


def test_cancel_terminal_state_returns_409(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    cancel_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """COMPLETED → cancel rejected → 409."""
    order = _make_order(customer_sub="user-1", status="COMPLETED")
    get_mock.return_value = order
    cancel_mock.side_effect = InvalidStatusTransitionError(
        "Cannot cancel order in status=COMPLETED"
    )
    token = make_jwt(roles=["tenant"], sub="user-1")
    resp = client.post(
        f"/api/v1/service-orders/{order.id}/cancel",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_cancel_with_empty_body_works(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    cancel_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Body optional per OpenAPI — reason=None в payload OK."""
    order = _make_order(customer_sub="user-1")
    get_mock.return_value = order
    cancelled = _make_order(customer_sub="user-1", status="CANCELLED", order_id=order.id)
    cancel_mock.return_value = cancelled

    token = make_jwt(roles=["tenant"], sub="user-1")
    resp = client.post(
        f"/api/v1/service-orders/{order.id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

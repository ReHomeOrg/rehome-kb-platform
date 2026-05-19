"""Unit tests для ServiceOrderRepository (#224, ТЗ §3.10.6).

Mock-session unit tests — state-machine transitions без БД. Drift
с CHECK constraints проверяется отдельно: `test_service_orders_check_sync`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.collaborators.service_orders_models import (
    ALLOWED_TRANSITIONS,
    ServiceOrder,
)
from src.api.collaborators.service_orders_repository import (
    InvalidStatusTransitionError,
    ServiceOrderRepository,
)


def _make_order(**over: object) -> ServiceOrder:
    o = ServiceOrder()
    o.id = uuid4()
    o.collaborator_id = uuid4()
    o.customer_sub = "user-1"
    o.premises_id = None
    o.booking_id = None
    o.service_type = "cleaning"
    o.service_description = None
    o.scheduled_at = None
    o.status = "PENDING_COLLABORATOR"
    o.price_rub = None
    o.commission_rub = None
    o.payment_status = "HOLD"
    o.customer_notes = None
    o.collaborator_notes = None
    o.cancel_reason = None
    o.created_at = datetime(2026, 5, 18, tzinfo=UTC)
    o.updated_at = datetime(2026, 5, 18, tzinfo=UTC)
    o.completed_at = None
    for k, v in over.items():
        setattr(o, k, v)
    return o


def _mock_session() -> MagicMock:
    s = MagicMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.refresh = AsyncMock()
    s.execute = AsyncMock()
    s.commit = AsyncMock()
    return s


# ---------------------------------------------------------------------------
# create


@pytest.mark.asyncio
async def test_create_sets_pending_collaborator_status() -> None:
    """Default status — `PENDING_COLLABORATOR` (sent to коллаборанту)."""
    session = _mock_session()
    repo = ServiceOrderRepository(session)
    collaborator_id = uuid4()
    await repo.create(
        collaborator_id=collaborator_id,
        customer_sub="user-1",
        service_type="cleaning",
    )
    session.add.assert_called_once()
    order: ServiceOrder = session.add.call_args.args[0]
    assert order.status == "PENDING_COLLABORATOR"
    assert order.payment_status == "HOLD"
    assert order.collaborator_id == collaborator_id
    assert order.customer_sub == "user-1"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_persists_optional_fields() -> None:
    """price_rub / commission_rub / premises_id / notes — passthrough."""
    session = _mock_session()
    repo = ServiceOrderRepository(session)
    premises_id = uuid4()
    await repo.create(
        collaborator_id=uuid4(),
        customer_sub="user-1",
        service_type="repair",
        premises_id=premises_id,
        price_rub=Decimal("3500.00"),
        commission_rub=Decimal("245.00"),
        customer_notes="Сломан кран",
    )
    order: ServiceOrder = session.add.call_args.args[0]
    assert order.premises_id == premises_id
    assert order.price_rub == Decimal("3500.00")
    assert order.commission_rub == Decimal("245.00")
    assert order.customer_notes == "Сломан кран"


# ---------------------------------------------------------------------------
# get_for_actor — ADR-0003 source-mask


@pytest.mark.asyncio
async def test_get_for_actor_staff_sees_others_orders() -> None:
    """Staff не filter'ится по customer_sub."""
    order = _make_order(customer_sub="other-user")
    session = _mock_session()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: order))
    repo = ServiceOrderRepository(session)
    got = await repo.get_for_actor(order.id, actor_sub="staff-1", is_staff=True)
    assert got is order


@pytest.mark.asyncio
async def test_get_for_actor_non_staff_query_filters_customer_sub() -> None:
    """Non-staff query содержит WHERE customer_sub = actor."""
    session = _mock_session()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    repo = ServiceOrderRepository(session)
    await repo.get_for_actor(uuid4(), actor_sub="user-2", is_staff=False)
    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "customer_sub" in compiled


# ---------------------------------------------------------------------------
# list_for_actor


@pytest.mark.asyncio
async def test_list_filters_to_own_orders_for_non_staff() -> None:
    session = _mock_session()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = ServiceOrderRepository(session)
    await repo.list_for_actor(actor_sub="user-3", is_staff=False)
    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "customer_sub" in compiled


@pytest.mark.asyncio
async def test_list_staff_no_customer_filter() -> None:
    session = _mock_session()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = ServiceOrderRepository(session)
    await repo.list_for_actor(actor_sub="staff-1", is_staff=True)
    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    # Staff query НЕ имеет customer_sub filter clause.
    assert "service_orders.customer_sub =" not in compiled
    assert "service_orders.customer_sub IS" not in compiled


# ---------------------------------------------------------------------------
# cancel — state machine


@pytest.mark.asyncio
async def test_cancel_from_pending_collaborator_works() -> None:
    order = _make_order(status="PENDING_COLLABORATOR")
    session = _mock_session()
    repo = ServiceOrderRepository(session)
    cancelled = await repo.cancel(order, reason="user changed mind")
    assert cancelled.status == "CANCELLED"
    assert cancelled.cancel_reason == "user changed mind"
    assert cancelled.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_from_in_progress_works() -> None:
    order = _make_order(status="IN_PROGRESS")
    session = _mock_session()
    repo = ServiceOrderRepository(session)
    cancelled = await repo.cancel(order, reason=None)
    assert cancelled.status == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_from_completed_rejected() -> None:
    """COMPLETED → CANCELLED не в ALLOWED_TRANSITIONS → InvalidStatusTransition."""
    order = _make_order(status="COMPLETED")
    session = _mock_session()
    repo = ServiceOrderRepository(session)
    with pytest.raises(InvalidStatusTransitionError):
        await repo.cancel(order, reason="too late")


@pytest.mark.asyncio
async def test_cancel_already_cancelled_rejected() -> None:
    """CANCELLED — terminal, no outgoing edges."""
    order = _make_order(status="CANCELLED")
    session = _mock_session()
    repo = ServiceOrderRepository(session)
    with pytest.raises(InvalidStatusTransitionError):
        await repo.cancel(order, reason=None)


# ---------------------------------------------------------------------------
# ALLOWED_TRANSITIONS spec


def test_terminal_states_have_no_outgoing_transitions() -> None:
    """CANCELLED / COMPLETED / FAILED — terminal except COMPLETED → DISPUTED."""
    assert ALLOWED_TRANSITIONS["CANCELLED"] == frozenset()
    assert ALLOWED_TRANSITIONS["FAILED"] == frozenset()
    # COMPLETED → DISPUTED — post-hoc claim path; isn't fully terminal.
    assert ALLOWED_TRANSITIONS["COMPLETED"] == frozenset({"DISPUTED"})


def test_all_transitions_target_known_states() -> None:
    """Каждый target в ALLOWED_TRANSITIONS — defined state."""
    from src.api.collaborators.service_orders_models import SERVICE_ORDER_STATUSES

    known = set(SERVICE_ORDER_STATUSES)
    for src_, dests in ALLOWED_TRANSITIONS.items():
        assert src_ in known
        for dest in dests:
            assert dest in known

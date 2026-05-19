"""Unit tests для PersonalDataRequestRepository (#232).

State machine + due_at calc + mark_overdue — mock session unit tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.admin.pd_requests_models import PersonalDataRequest
from src.api.admin.pd_requests_repository import (
    InvalidPdRequestTransitionError,
    PersonalDataRequestRepository,
)


def _make_request(**over: object) -> PersonalDataRequest:
    r = PersonalDataRequest()
    r.id = uuid4()
    r.type = "provide"
    r.status = "NEW"
    r.subject_id = uuid4()
    r.subject_email = "subject@example.com"
    r.subject_phone = None
    r.description = "Хочу копию ПДн"
    r.assigned_to = None
    r.created_at = datetime(2026, 5, 1, tzinfo=UTC)
    r.due_at = datetime(2026, 5, 31, tzinfo=UTC)
    r.completed_at = None
    r.resolution_note = None
    r.attachments = []
    r.updated_at = datetime(2026, 5, 1, tzinfo=UTC)
    for k, v in over.items():
        setattr(r, k, v)
    return r


def _session() -> MagicMock:
    s = MagicMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.execute = AsyncMock()
    return s


# ---------------------------------------------------------------------------
# create()


@pytest.mark.asyncio
async def test_create_sets_due_at_30_days() -> None:
    """ФЗ-152 §15: due_at = now + 30 days."""
    session = _session()
    repo = PersonalDataRequestRepository(session)
    before = datetime.now(UTC)
    await repo.create(
        type_="delete",
        subject_id=uuid4(),
        subject_email="x@y.com",
    )
    req = session.add.call_args.args[0]
    after = datetime.now(UTC)
    expected_min = before + timedelta(days=30)
    expected_max = after + timedelta(days=30)
    assert expected_min <= req.due_at <= expected_max
    assert req.status == "NEW"


@pytest.mark.asyncio
async def test_create_status_is_new() -> None:
    session = _session()
    repo = PersonalDataRequestRepository(session)
    await repo.create(type_="provide", subject_id=uuid4())
    req = session.add.call_args.args[0]
    assert req.status == "NEW"
    assert req.attachments == []


# ---------------------------------------------------------------------------
# State machine — update()


@pytest.mark.asyncio
async def test_transition_new_to_in_progress() -> None:
    r = _make_request(status="NEW")
    session = _session()
    repo = PersonalDataRequestRepository(session)
    await repo.update(r, status="IN_PROGRESS")
    assert r.status == "IN_PROGRESS"
    assert r.completed_at is None


@pytest.mark.asyncio
async def test_transition_in_progress_to_completed_sets_completed_at() -> None:
    r = _make_request(status="IN_PROGRESS")
    session = _session()
    repo = PersonalDataRequestRepository(session)
    await repo.update(r, status="COMPLETED", resolution_note="Data exported")
    assert r.status == "COMPLETED"
    assert r.completed_at is not None
    assert r.resolution_note == "Data exported"


@pytest.mark.asyncio
async def test_transition_new_to_rejected_sets_completed_at() -> None:
    r = _make_request(status="NEW")
    session = _session()
    repo = PersonalDataRequestRepository(session)
    await repo.update(r, status="REJECTED", resolution_note="Identity not verified")
    assert r.status == "REJECTED"
    assert r.completed_at is not None


@pytest.mark.asyncio
async def test_transition_new_to_completed_blocked() -> None:
    """NEW → COMPLETED не в ALLOWED_MANUAL_TRANSITIONS (skip IN_PROGRESS)."""
    r = _make_request(status="NEW")
    session = _session()
    repo = PersonalDataRequestRepository(session)
    with pytest.raises(InvalidPdRequestTransitionError):
        await repo.update(r, status="COMPLETED")


@pytest.mark.asyncio
async def test_transition_terminal_blocked() -> None:
    """COMPLETED → IN_PROGRESS blocked (reopen = new request)."""
    r = _make_request(status="COMPLETED", completed_at=datetime(2026, 5, 15, tzinfo=UTC))
    session = _session()
    repo = PersonalDataRequestRepository(session)
    with pytest.raises(InvalidPdRequestTransitionError):
        await repo.update(r, status="IN_PROGRESS")


@pytest.mark.asyncio
async def test_transition_overdue_to_in_progress() -> None:
    """OVERDUE → IN_PROGRESS allowed (рассмотрение продолжается)."""
    r = _make_request(status="OVERDUE")
    session = _session()
    repo = PersonalDataRequestRepository(session)
    await repo.update(r, status="IN_PROGRESS")
    assert r.status == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_completed_at_preserved_on_repeated_terminal_update() -> None:
    """COMPLETED → COMPLETED (с тем же status) → completed_at не trigger."""
    fixed = datetime(2026, 5, 10, tzinfo=UTC)
    r = _make_request(status="COMPLETED", completed_at=fixed)
    session = _session()
    repo = PersonalDataRequestRepository(session)
    await repo.update(r, resolution_note="updated note")
    assert r.completed_at == fixed
    assert r.resolution_note == "updated note"


@pytest.mark.asyncio
async def test_attachments_replace_not_merge() -> None:
    existing = [uuid4()]
    r = _make_request(attachments=existing)
    new = [uuid4(), uuid4()]
    session = _session()
    repo = PersonalDataRequestRepository(session)
    await repo.update(r, attachments=new)
    assert r.attachments == new
    assert existing[0] not in r.attachments


# ---------------------------------------------------------------------------
# list / get


@pytest.mark.asyncio
async def test_list_filter_status_and_type_in_sql() -> None:
    session = _session()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = PersonalDataRequestRepository(session)
    await repo.list_filtered(status="OVERDUE", type_filter="delete")
    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "status" in compiled
    assert "type" in compiled


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing() -> None:
    session = _session()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    repo = PersonalDataRequestRepository(session)
    assert await repo.get_by_id(uuid4()) is None


# ---------------------------------------------------------------------------
# mark_overdue — background worker helper


@pytest.mark.asyncio
async def test_mark_overdue_updates_matching_rows() -> None:
    """NEW/IN_PROGRESS с due_at < now → OVERDUE."""
    r1 = _make_request(status="NEW")
    r2 = _make_request(status="IN_PROGRESS")
    session = _session()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [r1, r2]))
    )
    repo = PersonalDataRequestRepository(session)
    count = await repo.mark_overdue()
    assert count == 2
    assert r1.status == "OVERDUE"
    assert r2.status == "OVERDUE"


@pytest.mark.asyncio
async def test_mark_overdue_no_rows_returns_zero() -> None:
    session = _session()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = PersonalDataRequestRepository(session)
    count = await repo.mark_overdue()
    assert count == 0
    # No flush call когда rows пусто (no-op).
    session.flush.assert_not_awaited()

"""Unit tests для PremisesCollaboratorRepository (Slice 5)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.collaborators.junction_repository import PremisesCollaboratorRepository
from src.api.collaborators.models import Collaborator, PremisesCollaborator


def _fake_session(rows: list[Any] | None = None) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.all = MagicMock(return_value=rows or [])
    result.rowcount = len(rows or [])
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _collab(group: str = "D") -> Collaborator:
    c = Collaborator()
    c.id = uuid4()
    c.financial_group = group
    return c


def _junction(premises_id: Any, collab_id: Any, role: str = "default_uk") -> PremisesCollaborator:
    pc = PremisesCollaborator()
    pc.id = uuid4()
    pc.premises_id = premises_id
    pc.collaborator_id = collab_id
    pc.role = role
    pc.priority = 1
    pc.notes = None
    pc.assigned_at = datetime(2026, 5, 17, tzinfo=UTC)
    pc.assigned_by = "staff"
    return pc


# ---------------------------------------------------------------------------
# list_for_premises


@pytest.mark.asyncio
async def test_list_empty_groups_short_circuits() -> None:
    session = _fake_session()
    repo = PremisesCollaboratorRepository(session)
    rows = await repo.list_for_premises(uuid4(), allowed_groups=frozenset())
    assert rows == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_list_applies_group_filter() -> None:
    pid = uuid4()
    c = _collab("D")
    pc = _junction(pid, c.id)
    session = _fake_session(rows=[(pc, c)])
    repo = PremisesCollaboratorRepository(session)
    result = await repo.list_for_premises(pid, allowed_groups=frozenset({"D"}))
    assert result == [(pc, c)]
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[Any] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert "D" in flat
    assert pid in flat


# ---------------------------------------------------------------------------
# assign


@pytest.mark.asyncio
async def test_assign_creates_row() -> None:
    session = _fake_session()
    repo = PremisesCollaboratorRepository(session)
    pc = await repo.assign(
        premises_id=uuid4(),
        collaborator_id=uuid4(),
        role="default_uk",
        priority=1,
        notes=None,
        assigned_by="staff",
    )
    assert pc is not None
    assert pc.role == "default_uk"
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_returns_none_on_duplicate() -> None:
    """IntegrityError (UQ violation) → None + rollback (не raise)."""
    from sqlalchemy.exc import IntegrityError

    session = _fake_session()
    session.flush = AsyncMock(side_effect=IntegrityError("x", "y", BaseException("dup")))
    repo = PremisesCollaboratorRepository(session)
    pc = await repo.assign(
        premises_id=uuid4(),
        collaborator_id=uuid4(),
        role="default_uk",
        priority=1,
        notes=None,
        assigned_by="staff",
    )
    assert pc is None
    session.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# remove


@pytest.mark.asyncio
async def test_remove_all_roles_no_role_arg() -> None:
    session = _fake_session()
    session.execute.return_value.rowcount = 2
    repo = PremisesCollaboratorRepository(session)
    deleted = await repo.remove(premises_id=uuid4(), collaborator_id=uuid4())
    assert deleted == 2


@pytest.mark.asyncio
async def test_remove_specific_role() -> None:
    session = _fake_session()
    session.execute.return_value.rowcount = 1
    repo = PremisesCollaboratorRepository(session)
    deleted = await repo.remove(
        premises_id=uuid4(), collaborator_id=uuid4(), role="emergency_water"
    )
    assert deleted == 1
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert "emergency_water" in flat

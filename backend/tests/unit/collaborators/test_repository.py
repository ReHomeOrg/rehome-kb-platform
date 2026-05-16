"""Unit tests для CollaboratorRepository — SQL compilation, защитные default'ы."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.collaborators.models import Collaborator
from src.api.collaborators.repository import CollaboratorRepository


def _fake_session(rows: list[Collaborator] | None = None) -> MagicMock:
    """MagicMock session — `.execute` возвращает result mock с `.scalars().all()`."""
    session = MagicMock()
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=lambda: rows or []))
    result.scalar_one_or_none = MagicMock(return_value=(rows[0] if rows else None))
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_collab(group: str = "D", type_: str = "management_company") -> Collaborator:
    c = Collaborator()
    c.id = uuid4()
    c.name = "Test УК"
    c.type = type_
    c.financial_group = group
    c.status = "ACTIVE"
    c.service_area = "Москва"
    c.contacts = []
    c.financial_terms = {}
    c.api_integration = {}
    c.sla = {}
    c.counterparty_check = {}
    c.audit_log = []
    c.updated_at = datetime(2026, 5, 16, tzinfo=UTC)
    return c


# ---------------------------------------------------------------------------
# list_filtered


@pytest.mark.asyncio
async def test_list_filtered_empty_groups_short_circuits() -> None:
    """Защитный default: пустой allowed_groups → ([], False) без SQL."""
    session = _fake_session()
    repo = CollaboratorRepository(session)
    rows, has_more = await repo.list_filtered(frozenset())
    assert rows == []
    assert has_more is False
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_list_filtered_applies_group_filter() -> None:
    session = _fake_session(rows=[_make_collab("D")])
    repo = CollaboratorRepository(session)
    await repo.list_filtered(frozenset({"D"}))
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[Any] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert "D" in flat


@pytest.mark.asyncio
async def test_list_filtered_type_filter() -> None:
    session = _fake_session()
    repo = CollaboratorRepository(session)
    await repo.list_filtered(frozenset({"A", "B", "C", "D"}), type_filter="management_company")
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert "management_company" in flat


@pytest.mark.asyncio
async def test_list_filtered_status_filter() -> None:
    session = _fake_session()
    repo = CollaboratorRepository(session)
    await repo.list_filtered(frozenset({"D"}), status="ACTIVE")
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert "ACTIVE" in flat


@pytest.mark.asyncio
async def test_list_filtered_service_area_uses_ilike_wildcards() -> None:
    """service_area — ILIKE %area% для substring matching."""
    session = _fake_session()
    repo = CollaboratorRepository(session)
    await repo.list_filtered(frozenset({"D"}), service_area="Москва")
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert "%Москва%" in flat


@pytest.mark.asyncio
async def test_list_filtered_has_more_when_limit_plus_one_returned() -> None:
    rows = [_make_collab() for _ in range(21)]
    session = _fake_session(rows=rows)
    repo = CollaboratorRepository(session)
    result_rows, has_more = await repo.list_filtered(frozenset({"D"}), limit=20)
    assert len(result_rows) == 20
    assert has_more is True


# ---------------------------------------------------------------------------
# get_by_id


@pytest.mark.asyncio
async def test_get_by_id_empty_groups_returns_none() -> None:
    session = _fake_session()
    repo = CollaboratorRepository(session)
    result = await repo.get_by_id(uuid4(), frozenset())
    assert result is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_by_id_filters_by_group() -> None:
    c = _make_collab("D")
    session = _fake_session(rows=[c])
    repo = CollaboratorRepository(session)
    result = await repo.get_by_id(c.id, frozenset({"D"}))
    assert result is c
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[Any] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert "D" in flat
    assert c.id in flat


# ---------------------------------------------------------------------------
# create / update / archive


@pytest.mark.asyncio
async def test_create_adds_and_flushes() -> None:
    session = _fake_session()
    repo = CollaboratorRepository(session)
    c = _make_collab()
    result = await repo.create(c)
    assert result is c
    session.add.assert_called_once_with(c)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_fields_applies_partial_update() -> None:
    session = _fake_session()
    repo = CollaboratorRepository(session)
    c = _make_collab()
    await repo.update_fields(c, {"name": "Новое имя"})
    assert c.name == "Новое имя"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_fields_flags_jsonb_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSONB field updates требуют flag_modified — иначе SQLAlchemy
    не запишет."""
    calls: list[tuple[Collaborator, str]] = []

    def _spy(target: Collaborator, name: str) -> None:
        calls.append((target, name))

    monkeypatch.setattr("src.api.collaborators.repository.flag_modified", _spy)
    session = _fake_session()
    repo = CollaboratorRepository(session)
    c = _make_collab()
    await repo.update_fields(c, {"contacts": [{"phone": "+7..."}]})
    assert len(calls) == 1
    assert calls[0][1] == "contacts"


@pytest.mark.asyncio
async def test_archive_sets_status_archived() -> None:
    session = _fake_session()
    repo = CollaboratorRepository(session)
    c = _make_collab()
    c.status = "ACTIVE"
    await repo.archive(c)
    assert c.status == "ARCHIVED"
    session.flush.assert_awaited_once()

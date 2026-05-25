"""Unit tests для CategoryAdminRepository (ADR-0024, #355)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.categories.admin_repository import (
    ArchivedParentError,
    CategoryAdminRepository,
    CycleDetectedError,
    ParentNotFoundError,
    SlugConflictError,
)
from src.api.categories.models import Category


def _make_category(**over: Any) -> Category:
    c = Category()
    c.id = over.get("id", uuid4())
    c.slug = over.get("slug", "x")
    c.title = over.get("title", "X")
    c.description = over.get("description")
    c.parent_id = over.get("parent_id")
    c.created_at = datetime.now(UTC)
    c.updated_at = datetime.now(UTC)
    c.archived_at = over.get("archived_at")
    return c


def _session_with(scalar_returns: list[Any] | None = None) -> Any:
    """Sequenced execute results — каждый call возвращает next item."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    if scalar_returns is None:
        scalar_returns = [None]
    results = []
    for val in scalar_returns:
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=val)
        results.append(r)
    session.execute = AsyncMock(side_effect=results)
    return session


# ---------------------------------------------------------------------------
# create


@pytest.mark.asyncio
async def test_create_rejects_duplicate_slug() -> None:
    existing = _make_category(slug="x")
    session = _session_with([existing])
    repo = CategoryAdminRepository(session)
    with pytest.raises(SlugConflictError):
        await repo.create(slug="x", title="X", description=None, parent_id=None)


@pytest.mark.asyncio
async def test_create_rejects_unknown_parent() -> None:
    # Call 1: slug check (None — no conflict). Call 2: parent lookup (None).
    session = _session_with([None, None])
    repo = CategoryAdminRepository(session)
    with pytest.raises(ParentNotFoundError):
        await repo.create(slug="x", title="X", description=None, parent_id=uuid4())


@pytest.mark.asyncio
async def test_create_rejects_archived_parent() -> None:
    archived_parent = _make_category(slug="p", archived_at=datetime.now(UTC))
    # Call 1: slug check (None). Call 2: parent lookup → archived.
    session = _session_with([None, archived_parent])
    repo = CategoryAdminRepository(session)
    with pytest.raises(ArchivedParentError):
        await repo.create(slug="x", title="X", description=None, parent_id=archived_parent.id)


@pytest.mark.asyncio
async def test_create_root_category_succeeds() -> None:
    session = _session_with([None])
    repo = CategoryAdminRepository(session)
    row = await repo.create(slug="root", title="Root", description=None, parent_id=None)
    assert row.slug == "root"
    assert row.parent_id is None
    session.add.assert_called_once()
    session.flush.assert_awaited()


# ---------------------------------------------------------------------------
# update — cycle detection


@pytest.mark.asyncio
async def test_update_parent_id_self_raises_cycle() -> None:
    category = _make_category(slug="x")
    session = _session_with([])
    repo = CategoryAdminRepository(session)
    with pytest.raises(CycleDetectedError, match="не может равняться id"):
        await repo.update(category, parent_id=category.id, parent_id_set=True)


@pytest.mark.asyncio
async def test_update_parent_chain_cycle_detected() -> None:
    """A → B → A: PATCH A.parent_id = B; B.parent_id = A → cycle.

    Walking от B вверх через parent_id chain даёт A → CycleDetectedError.
    """
    cat_a = _make_category(slug="a")
    cat_b = _make_category(slug="b", parent_id=cat_a.id)
    # Sequence: lookup parent (B) → walks chain → B.parent_id (= A).
    session = _session_with([cat_b, cat_a.id])
    repo = CategoryAdminRepository(session)
    with pytest.raises(CycleDetectedError, match="cycle"):
        await repo.update(cat_a, parent_id=cat_b.id, parent_id_set=True)


@pytest.mark.asyncio
async def test_update_parent_id_valid_change_succeeds() -> None:
    """A → B (B is root, A is child). Move A under C (also root) — OK."""
    cat_a = _make_category(slug="a")
    cat_c = _make_category(slug="c")  # new parent — root
    # Sequence: lookup C → walks chain from C → None (root).
    session = _session_with([cat_c, None])
    repo = CategoryAdminRepository(session)
    result = await repo.update(cat_a, parent_id=cat_c.id, parent_id_set=True)
    assert result.parent_id == cat_c.id


@pytest.mark.asyncio
async def test_update_parent_to_none_promotes_to_root() -> None:
    """PATCH parent_id=None (explicit) — promotes к root, no cycle check."""
    cat = _make_category(slug="x", parent_id=uuid4())
    session = _session_with([])
    repo = CategoryAdminRepository(session)
    result = await repo.update(cat, parent_id=None, parent_id_set=True)
    assert result.parent_id is None


@pytest.mark.asyncio
async def test_update_title_only_no_parent_walk() -> None:
    """Title change без parent_id touch — no parent lookup."""
    cat = _make_category(slug="x")
    session = _session_with([])  # no execute calls expected
    repo = CategoryAdminRepository(session)
    result = await repo.update(cat, title="New Title", parent_id_set=False)
    assert result.title == "New Title"


@pytest.mark.asyncio
async def test_update_to_archived_parent_rejected() -> None:
    cat = _make_category(slug="x")
    archived = _make_category(slug="p", archived_at=datetime.now(UTC))
    session = _session_with([archived])
    repo = CategoryAdminRepository(session)
    with pytest.raises(ArchivedParentError):
        await repo.update(cat, parent_id=archived.id, parent_id_set=True)


@pytest.mark.asyncio
async def test_update_deep_parent_chain_no_cycle() -> None:
    """A → B → C → D — PATCH A under D — walks chain D→C→B→ None, OK."""
    cat_a = _make_category(slug="a")
    cat_b_id = uuid4()
    cat_c_id = uuid4()
    cat_d = _make_category(slug="d")
    # Sequence: lookup D → walks D.parent (= C.id) → C.parent (= B.id) →
    # B.parent (= None root).
    session = _session_with([cat_d, cat_c_id, cat_b_id, None])
    repo = CategoryAdminRepository(session)
    result = await repo.update(cat_a, parent_id=cat_d.id, parent_id_set=True)
    assert result.parent_id == cat_d.id


@pytest.mark.asyncio
async def test_corrupted_loop_raises_cycle() -> None:
    """B.parent → C; C.parent → B (pre-existing corrupt loop без target).
    Walking detects revisit → CycleDetectedError."""
    cat_x = _make_category(slug="x")
    cat_b = _make_category(slug="b")
    # Walk: B → C.id → B.id (revisit) → raise.
    cat_c_id = uuid4()
    session = _session_with([cat_b, cat_c_id, cat_b.id])
    repo = CategoryAdminRepository(session)
    with pytest.raises(CycleDetectedError, match="pre-existing cycle"):
        await repo.update(cat_x, parent_id=cat_b.id, parent_id_set=True)


# ---------------------------------------------------------------------------
# archive


@pytest.mark.asyncio
async def test_archive_sets_timestamp() -> None:
    cat = _make_category(slug="x")
    assert cat.archived_at is None
    session = _session_with([])
    repo = CategoryAdminRepository(session)
    result = await repo.archive(cat)
    assert result.archived_at is not None


@pytest.mark.asyncio
async def test_archive_idempotent() -> None:
    """Already-archived — повторный archive() не обновляет timestamp."""
    original_ts = datetime(2026, 1, 1, tzinfo=UTC)
    cat = _make_category(slug="x", archived_at=original_ts)
    session = _session_with([])
    repo = CategoryAdminRepository(session)
    result = await repo.archive(cat)
    assert result.archived_at == original_ts
    session.flush.assert_not_called()


# ---------------------------------------------------------------------------
# list_all


@pytest.mark.asyncio
async def test_list_all_default_excludes_archived() -> None:
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result_mock)
    repo = CategoryAdminRepository(session)
    await repo.list_all()
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile()).lower()
    assert "archived_at is null" in sql


@pytest.mark.asyncio
async def test_list_all_include_archived_omits_filter() -> None:
    session = MagicMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result_mock)
    repo = CategoryAdminRepository(session)
    await repo.list_all(include_archived=True)
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile()).lower()
    assert "archived_at is null" not in sql

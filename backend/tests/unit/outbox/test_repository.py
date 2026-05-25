"""Unit tests для OutboxRepository (#356, ADR-0026 Slice 0)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.outbox.models import OutboxRow
from src.api.outbox.repository import OutboxRepository


def _session_stub(rows: list[OutboxRow] | None = None) -> Any:
    """Mock session: execute() returns result with scalars().all()."""
    session = MagicMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows or []
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_enqueue_adds_row_no_commit() -> None:
    """`enqueue` использует external session — НЕ commit'ит сам."""
    session = _session_stub()
    repo = OutboxRepository(session)
    row = await repo.enqueue(event_type="article.published", payload={"id": "x"})
    assert isinstance(row, OutboxRow)
    assert row.event_type == "article.published"
    assert row.payload == {"id": "x"}
    session.add.assert_called_once()
    # Critical invariant: enqueue НЕ делает commit (caller responsible).
    assert not hasattr(session, "commit") or not session.commit.called


@pytest.mark.asyncio
async def test_fetch_unflushed_filters_and_orders() -> None:
    """SQL должен иметь WHERE flushed_at IS NULL + ORDER BY created_at ASC."""
    session = _session_stub([])
    repo = OutboxRepository(session)
    await repo.fetch_unflushed(limit=10)
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile()).lower()
    assert "flushed_at is null" in sql
    assert "order by outbox.created_at asc" in sql
    assert "limit" in sql


@pytest.mark.asyncio
async def test_mark_flushed_emits_update_with_now() -> None:
    """`mark_flushed` issues UPDATE setting flushed_at to non-null."""
    session = _session_stub()
    repo = OutboxRepository(session)
    row_id = uuid4()
    await repo.mark_flushed(row_id)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    sql = str(compiled).lower()
    assert "update outbox" in sql
    assert "set flushed_at" in sql


@pytest.mark.asyncio
async def test_record_failure_increments_and_stores_error() -> None:
    """`record_failure` bumps retries + stores truncated last_error."""
    session = _session_stub()
    repo = OutboxRepository(session)
    row_id = uuid4()
    await repo.record_failure(row_id, error="Boom!")
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert "Boom!" in flat


@pytest.mark.asyncio
async def test_record_failure_truncates_long_error() -> None:
    """Last_error capped на 2000 chars — anti-DoS на huge tracebacks."""
    session = _session_stub()
    repo = OutboxRepository(session)
    huge = "X" * 5000
    await repo.record_failure(uuid4(), error=huge)
    compiled = session.execute.call_args.args[0].compile(
        compile_kwargs={"literal_binds": False}
    )
    flat = list(compiled.params.values())
    truncated = next(v for v in flat if isinstance(v, str) and v.startswith("X"))
    assert len(truncated) == 2000

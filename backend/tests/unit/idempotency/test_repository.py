"""Unit-тесты IdempotencyKeyRepository (E5.1 #44)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.idempotency.models import IdempotencyKey
from src.api.idempotency.repository import IdempotencyKeyRepository


@pytest.mark.asyncio
async def test_get_returns_none_when_not_found() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    repo = IdempotencyKeyRepository(session)
    out = await repo.get("key", "/path", "actor")
    assert out is None


@pytest.mark.asyncio
async def test_get_returns_stored_entry() -> None:
    entry = IdempotencyKey(
        key="key",
        request_path="/path",
        actor_sub="actor",
        request_body_hash="hash",
        response_status=201,
        response_body={"id": "x"},
        response_headers={"Location": "/a/x"},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = entry
    session.execute = AsyncMock(return_value=result)
    repo = IdempotencyKeyRepository(session)
    out = await repo.get("key", "/path", "actor")
    assert out is entry


@pytest.mark.asyncio
async def test_get_sql_filters_by_expires_at() -> None:
    """ADR — expired entries отсекаются на SQL уровне."""
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = IdempotencyKeyRepository(session)
    await repo.get("key", "/path", "actor")
    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    # expires_at > now() — filter.
    assert "expires_at" in sql
    # PK filter.
    assert "key" in sql
    assert "request_path" in sql
    assert "actor_sub" in sql


@pytest.mark.asyncio
async def test_save_inserts_entry_with_24h_ttl() -> None:
    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.flush = AsyncMock(return_value=None)
    repo = IdempotencyKeyRepository(session)
    entry = await repo.save(
        key="k",
        path="/p",
        actor_sub="a",
        request_body_hash="h",
        response_status=201,
        response_body={"data": 1},
        response_headers={"H": "v"},
    )
    assert len(added) == 1
    assert isinstance(added[0], IdempotencyKey)
    assert entry.response_status == 201
    # TTL ~24h
    delta = entry.expires_at - datetime.now(UTC)
    assert timedelta(hours=23, minutes=55) <= delta <= timedelta(hours=24, minutes=5)


@pytest.mark.asyncio
@pytest.mark.security
async def test_acquire_lock_executes_pg_advisory_xact_lock() -> None:
    """SQL inspection: pg_advisory_xact_lock с правильным composite hash."""
    captured: list[Any] = []

    async def _capture(stmt: Any) -> Any:
        captured.append(stmt)
        return MagicMock()

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = IdempotencyKeyRepository(session)
    await repo.acquire_lock("the-key", "/path", "actor-sub")
    assert len(captured) == 1
    sql = str(captured[0])
    assert "pg_advisory_xact_lock" in sql
    assert "hashtext" in sql
    # composite bind param используется (не literal).
    params = captured[0].compile().params
    assert "the-key|/path|actor-sub" in params.values()

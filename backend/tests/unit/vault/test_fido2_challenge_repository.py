"""Unit tests для VaultFIDO2ChallengeRepository (ADR-0022 A)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.vault.fido2_repository import (
    CHALLENGE_TTL,
    VaultFIDO2ChallengeRepository,
)
from src.api.vault.models import VaultFIDO2Challenge


def _make_challenge(
    *, ceremony: str = "registration", expires_in: timedelta | None = None
) -> VaultFIDO2Challenge:
    c = VaultFIDO2Challenge()
    c.challenge = b"\xaa" * 64
    c.user_id = uuid4()
    c.ceremony = ceremony
    c.created_at = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    c.expires_at = c.created_at + (expires_in or CHALLENGE_TTL)
    return c


@pytest.mark.asyncio
async def test_create_rejects_invalid_ceremony() -> None:
    repo = VaultFIDO2ChallengeRepository(MagicMock())
    with pytest.raises(ValueError, match="Invalid ceremony"):
        await repo.create(
            challenge=b"\x01" * 32,
            user_id=uuid4(),
            ceremony="hacker",
        )


@pytest.mark.asyncio
async def test_create_persists_with_ttl() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    repo = VaultFIDO2ChallengeRepository(session)

    now = datetime(2026, 5, 20, tzinfo=UTC)
    await repo.create(
        challenge=b"\x01" * 32,
        user_id=uuid4(),
        ceremony="registration",
        now=now,
    )
    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    assert row.ceremony == "registration"
    assert row.expires_at == now + CHALLENGE_TTL


@pytest.mark.asyncio
async def test_consume_valid_challenge_deletes_row() -> None:
    row = _make_challenge()
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = lambda: row
    session.execute = AsyncMock(return_value=result)
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    repo = VaultFIDO2ChallengeRepository(session)

    ok = await repo.consume(
        challenge=row.challenge,
        user_id=row.user_id,
        ceremony="registration",
        now=row.created_at,
    )
    assert ok is True
    session.delete.assert_awaited_once_with(row)


@pytest.mark.asyncio
async def test_consume_missing_challenge_returns_false() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = lambda: None
    session.execute = AsyncMock(return_value=result)
    session.delete = AsyncMock()
    repo = VaultFIDO2ChallengeRepository(session)

    ok = await repo.consume(
        challenge=b"\x00" * 32,
        user_id=uuid4(),
        ceremony="registration",
    )
    assert ok is False
    session.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_consume_expired_challenge_returns_false() -> None:
    """Challenge past expires_at → не consumed, не deleted."""
    row = _make_challenge(expires_in=timedelta(seconds=-10))
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = lambda: row
    session.execute = AsyncMock(return_value=result)
    session.delete = AsyncMock()
    repo = VaultFIDO2ChallengeRepository(session)

    ok = await repo.consume(
        challenge=row.challenge,
        user_id=row.user_id,
        ceremony="registration",
        now=row.created_at,
    )
    assert ok is False
    session.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_consume_is_single_use() -> None:
    """Повторный consume того же challenge возвращает False (delete already)."""
    session = MagicMock()
    # 1st call returns row, 2nd returns None (simulating deleted state).
    row = _make_challenge()
    result1 = MagicMock()
    result1.scalar_one_or_none = lambda: row
    result2 = MagicMock()
    result2.scalar_one_or_none = lambda: None
    session.execute = AsyncMock(side_effect=[result1, result2])
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    repo = VaultFIDO2ChallengeRepository(session)

    assert (
        await repo.consume(
            challenge=row.challenge,
            user_id=row.user_id,
            ceremony="registration",
            now=row.created_at,
        )
        is True
    )
    assert (
        await repo.consume(
            challenge=row.challenge,
            user_id=row.user_id,
            ceremony="registration",
            now=row.created_at,
        )
        is False
    )


@pytest.mark.asyncio
async def test_reap_expired_returns_rowcount() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=7))
    repo = VaultFIDO2ChallengeRepository(session)
    assert await repo.reap_expired() == 7

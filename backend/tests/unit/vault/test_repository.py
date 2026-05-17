"""Unit tests для VaultRepository — SQL inspection (#146)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.vault.repository import VaultRepository


@pytest.mark.asyncio
async def test_get_user_filters_by_user_id() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    repo = VaultRepository(session)
    uid = uuid4()
    await repo.get_user(uid)
    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    assert uid in compiled.params.values()


@pytest.mark.asyncio
async def test_is_group_member_returns_true_when_found() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: MagicMock()))
    repo = VaultRepository(session)
    assert await repo.is_group_member(uuid4(), uuid4()) is True


@pytest.mark.asyncio
async def test_is_group_member_returns_false_when_not_found() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    repo = VaultRepository(session)
    assert await repo.is_group_member(uuid4(), uuid4()) is False


@pytest.mark.asyncio
async def test_get_wraps_for_recipient_user_only() -> None:
    """Без group_ids — query filtter'ит только по user_id."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = VaultRepository(session)
    uid, sid = uuid4(), uuid4()
    await repo.get_wraps_for_recipient(secret_id=sid, user_id=uid, user_group_ids=[])
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert uid in flat
    assert sid in flat


@pytest.mark.asyncio
async def test_get_wraps_for_recipient_ignores_groups_post_adr_0017() -> None:
    """ADR-0017: group_ids — pure metadata, не authorization. Query
    содержит только user_id, без OR-branch на groups."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = VaultRepository(session)
    uid, sid, gid = uuid4(), uuid4(), uuid4()
    await repo.get_wraps_for_recipient(secret_id=sid, user_id=uid, user_group_ids=[gid])
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert uid in flat
    assert sid in flat
    # group_id больше не входит в access query (lineage only).
    assert gid not in flat


@pytest.mark.asyncio
async def test_can_user_access_secret_no_wraps() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = VaultRepository(session)
    can = await repo.can_user_access_secret(secret_id=uuid4(), user_id=uuid4(), user_group_ids=[])
    assert can is False


@pytest.mark.asyncio
async def test_can_user_access_secret_with_wrap() -> None:
    session = MagicMock()
    mock_wrap = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [mock_wrap]))
    )
    repo = VaultRepository(session)
    can = await repo.can_user_access_secret(secret_id=uuid4(), user_id=uuid4(), user_group_ids=[])
    assert can is True

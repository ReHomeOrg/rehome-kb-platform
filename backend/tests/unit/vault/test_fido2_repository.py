"""Unit tests для VaultFIDO2Repository (ADR-0022 A)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.api.vault.fido2_repository import (
    MAX_KEYS_PER_USER,
    VaultFIDO2CapacityError,
    VaultFIDO2Repository,
)
from src.api.vault.models import VaultFIDO2Credential


def _make_cred(user_id: UUID | None = None) -> VaultFIDO2Credential:
    c = VaultFIDO2Credential()
    c.id = uuid4()
    c.user_id = user_id if user_id is not None else uuid4()
    c.credential_id = b"\x01" * 32
    c.public_key = b"\x02" * 64
    c.sign_count = 0
    c.transports = ["usb", "nfc"]
    c.aaguid = b"\x00" * 16
    c.nickname = "YubiKey"
    c.created_at = datetime(2026, 5, 20, tzinfo=UTC)
    c.last_used_at = None
    return c


def _session_with_scalars(rows: list[VaultFIDO2Credential]) -> MagicMock:
    """Mock async session returning rows from execute(stmt).scalars().all()."""
    session = MagicMock()
    result = MagicMock()
    result.scalars = lambda: MagicMock(all=lambda: rows)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# list_by_user / count_by_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_by_user_returns_rows() -> None:
    cred = _make_cred()
    session = _session_with_scalars([cred])
    repo = VaultFIDO2Repository(session)

    rows = await repo.list_by_user(cred.user_id)
    assert rows == [cred]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_count_by_user_returns_length() -> None:
    creds = [_make_cred(), _make_cred()]
    session = _session_with_scalars(creds)
    repo = VaultFIDO2Repository(session)
    assert await repo.count_by_user(uuid4()) == 2


# ---------------------------------------------------------------------------
# get_by_credential_id / get_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_credential_id_returns_match() -> None:
    cred = _make_cred()
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = lambda: cred
    session.execute = AsyncMock(return_value=result)
    repo = VaultFIDO2Repository(session)

    found = await repo.get_by_credential_id(cred.credential_id)
    assert found is cred


@pytest.mark.asyncio
async def test_get_by_credential_id_returns_none_when_missing() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = lambda: None
    session.execute = AsyncMock(return_value=result)
    repo = VaultFIDO2Repository(session)

    assert await repo.get_by_credential_id(b"unknown") is None


@pytest.mark.asyncio
async def test_get_by_id_scoped_to_user() -> None:
    """Anti-tamper: get_by_id обязан filter по user_id."""
    user_id = uuid4()
    cred_pk = uuid4()
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = lambda: None
    session.execute = AsyncMock(return_value=result)
    repo = VaultFIDO2Repository(session)

    await repo.get_by_id(cred_pk, user_id=user_id)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    params = list(compiled.params.values())
    # Both user_id и id участвуют в WHERE.
    assert user_id in params
    assert cred_pk in params


# ---------------------------------------------------------------------------
# create — capacity enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_succeeds_when_under_cap() -> None:
    user_id = uuid4()
    session = _session_with_scalars([])  # 0 existing
    repo = VaultFIDO2Repository(session)

    cred = await repo.create(
        user_id=user_id,
        credential_id=b"\x10" * 32,
        public_key=b"\x20" * 64,
        transports=["usb"],
        nickname="Test Key",
    )

    session.add.assert_called_once()
    added = session.add.call_args.args[0]
    assert added.user_id == user_id
    assert added.credential_id == b"\x10" * 32
    assert added.transports == ["usb"]
    assert added.nickname == "Test Key"
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(added)
    assert cred is added


@pytest.mark.asyncio
async def test_create_rejects_when_at_cap() -> None:
    """User уже имеет MAX_KEYS_PER_USER credentials → ValueError."""
    user_id = uuid4()
    full_set = [_make_cred(user_id) for _ in range(MAX_KEYS_PER_USER)]
    session = _session_with_scalars(full_set)
    repo = VaultFIDO2Repository(session)

    with pytest.raises(VaultFIDO2CapacityError, match=f"Max {MAX_KEYS_PER_USER}"):
        await repo.create(
            user_id=user_id,
            credential_id=b"\x10" * 32,
            public_key=b"\x20" * 64,
            transports=[],
        )

    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# update_sign_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_sign_count_bumps_counter_and_last_used() -> None:
    cred = _make_cred()
    cred.sign_count = 5
    session = MagicMock()
    session.get = AsyncMock(return_value=cred)
    session.flush = AsyncMock()
    repo = VaultFIDO2Repository(session)

    await repo.update_sign_count(cred.id, new_sign_count=42)
    assert cred.sign_count == 42
    assert cred.last_used_at is not None
    assert cred.last_used_at.tzinfo is UTC
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_sign_count_noops_if_credential_missing() -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    repo = VaultFIDO2Repository(session)

    await repo.update_sign_count(uuid4(), new_sign_count=42)
    session.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# delete_by_id — user_id scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_returns_true_when_deleted() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    repo = VaultFIDO2Repository(session)

    assert await repo.delete_by_id(uuid4(), user_id=uuid4()) is True


@pytest.mark.asyncio
async def test_delete_returns_false_when_not_owned() -> None:
    """Cross-user delete attempt → 0 rows affected → False."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    repo = VaultFIDO2Repository(session)

    assert await repo.delete_by_id(uuid4(), user_id=uuid4()) is False


@pytest.mark.asyncio
async def test_delete_includes_user_id_in_where() -> None:
    """Security: DELETE WHERE id = X AND user_id = Y — both clauses."""
    user_id = uuid4()
    cred_pk = uuid4()
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    repo = VaultFIDO2Repository(session)

    await repo.delete_by_id(cred_pk, user_id=user_id)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    params = list(compiled.params.values())
    assert user_id in params
    assert cred_pk in params

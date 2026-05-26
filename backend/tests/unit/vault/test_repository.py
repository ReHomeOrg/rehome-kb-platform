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


# ---------------------------------------------------------------------------
# ADR-0017 §E rotate_secret_atomic


@pytest.mark.asyncio
async def test_rotate_secret_atomic_version_mismatch_returns_none() -> None:
    """Если payload_version != expected_version — None, без mutations."""
    from src.api.vault.models import VaultSecretBlob

    blob = VaultSecretBlob()
    blob.secret_id = uuid4()
    blob.ciphertext = b"old"
    blob.payload_version = 5  # actual version
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: blob))
    session.flush = AsyncMock()
    session.add = MagicMock()
    repo = VaultRepository(session)

    result = await repo.rotate_secret_atomic(
        secret_id=blob.secret_id,
        new_title_ciphertext=b"new-title",
        new_ciphertext=b"new",
        expected_version=1,  # mismatch — caller думает версия 1
        new_wraps=[],
    )
    assert result is None
    # Blob НЕ был изменён — ни ciphertext, ни version.
    assert blob.ciphertext == b"old"
    assert blob.payload_version == 5
    # session.add НЕ вызывался для new_wraps (early return).
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_rotate_secret_atomic_no_blob_returns_none() -> None:
    """Secret deleted между fetch и rotate — None."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    session.flush = AsyncMock()
    repo = VaultRepository(session)
    result = await repo.rotate_secret_atomic(
        secret_id=uuid4(),
        new_title_ciphertext=b"new-title",
        new_ciphertext=b"new",
        expected_version=1,
        new_wraps=[],
    )
    assert result is None


@pytest.mark.asyncio
async def test_list_secret_wraps_returns_all_recipients_ordered() -> None:
    """list_secret_wraps SQL: SELECT * WHERE secret_id = ? ORDER BY user_id."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = VaultRepository(session)
    sid = uuid4()
    await repo.list_secret_wraps(sid)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    sql = str(compiled).lower()
    assert "from vault_secret_wraps" in sql
    assert "secret_id" in sql
    assert "order by" in sql
    assert "user_id" in sql
    # secret_id param привязан.
    assert sid in compiled.params.values()


@pytest.mark.asyncio
async def test_rotate_secret_atomic_happy_path_updates_blob_and_bumps_version() -> None:
    """Version match → blob.ciphertext + payload_version updated; title
    updated; wraps deleted + re-inserted; session.flush'нут."""
    from src.api.vault.models import VaultSecret, VaultSecretBlob, VaultSecretWrap

    secret = VaultSecret()
    secret.id = uuid4()
    secret.title_ciphertext = b"old-title"
    blob = VaultSecretBlob()
    blob.secret_id = secret.id
    blob.ciphertext = b"old"
    blob.payload_version = 1
    session = MagicMock()
    # 1-й execute — SELECT FOR UPDATE blob; 2-й — DELETE wraps; 3-й —
    # get_secret (для title update).
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: blob),
            MagicMock(),  # DELETE result
            MagicMock(scalar_one_or_none=lambda: secret),  # get_secret
        ]
    )
    session.flush = AsyncMock()
    session.add = MagicMock()
    repo = VaultRepository(session)

    new_wraps = [
        VaultSecretWrap(user_id=uuid4(), group_id=None, wrapped_key=b"\x10" * 64),
        VaultSecretWrap(user_id=uuid4(), group_id=None, wrapped_key=b"\x11" * 64),
    ]
    result = await repo.rotate_secret_atomic(
        secret_id=blob.secret_id,
        new_title_ciphertext=b"new-title",
        new_ciphertext=b"new-payload",
        expected_version=1,
        new_wraps=new_wraps,
    )
    assert result is blob
    assert blob.ciphertext == b"new-payload"
    assert blob.payload_version == 2
    # Title тоже обновлён (тот же secret_key зашифровал).
    assert secret.title_ciphertext == b"new-title"
    # SELECT blob + DELETE wraps + SELECT secret = 3 execute call'а.
    assert session.execute.await_count == 3
    assert session.add.call_count == 2
    session.flush.assert_awaited_once()

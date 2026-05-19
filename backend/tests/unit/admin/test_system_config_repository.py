"""Unit tests для SystemConfigRepository (#264, ADR-0019)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.admin.system_config_repository import (
    MUTABLE_KEYS,
    SystemConfigRepository,
    UnknownKeyError,
)


def _session_with_row(initial: dict[str, Any] | None = None) -> tuple[Any, Any]:
    """Build mock AsyncSession that returns a row with given data."""
    row = MagicMock()
    row.id = 1
    row.data = initial or {}
    row.updated_by = "system_init"

    result = MagicMock()
    result.scalar_one_or_none.return_value = row

    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session, row


@pytest.mark.asyncio
async def test_read_returns_current_overlay() -> None:
    session, _ = _session_with_row({"llm_provider": "mock"})
    repo = SystemConfigRepository(session)
    result = await repo.read()
    assert result == {"llm_provider": "mock"}


@pytest.mark.asyncio
async def test_patch_writes_allowed_key() -> None:
    session, row = _session_with_row()
    repo = SystemConfigRepository(session)
    result = await repo.patch({"llm_provider": "gigachat"}, actor_sub="admin-1")
    assert result == {"llm_provider": "gigachat"}
    assert row.data == {"llm_provider": "gigachat"}
    assert row.updated_by == "admin-1"


@pytest.mark.asyncio
async def test_patch_merges_with_existing_data() -> None:
    session, row = _session_with_row({"llm_provider": "mock"})
    repo = SystemConfigRepository(session)
    result = await repo.patch({"feature_flags.rag_enabled": False}, actor_sub="admin-1")
    # Both keys preserved.
    assert result == {
        "llm_provider": "mock",
        "feature_flags.rag_enabled": False,
    }


@pytest.mark.asyncio
async def test_patch_rejects_unknown_key() -> None:
    session, _ = _session_with_row()
    repo = SystemConfigRepository(session)
    with pytest.raises(UnknownKeyError) as exc:
        await repo.patch({"sensitive_key": "value"}, actor_sub="admin-1")
    assert "sensitive_key" in exc.value.keys


@pytest.mark.asyncio
async def test_patch_empty_updates_no_op() -> None:
    session, row = _session_with_row({"llm_provider": "mock"})
    repo = SystemConfigRepository(session)
    result = await repo.patch({}, actor_sub="admin-1")
    assert result == {"llm_provider": "mock"}
    # No update flushed because no changes — we only flush after row mutation.
    # session.execute called только для _get_row (1 раз).


def test_mutable_keys_does_not_include_secrets() -> None:
    """Defensive: paranoid check что allowlist не содержит sensitive keys."""
    for key in MUTABLE_KEYS:
        assert "password" not in key.lower()
        assert "secret" not in key.lower()
        assert "key" not in key.lower() or key.startswith("feature_flags")
        assert "token" not in key.lower()

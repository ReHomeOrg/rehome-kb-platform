"""Unit-тесты AuditRepository (E4.x #102)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.audit.models import AuditLog
from src.api.audit.repository import AuditRepository


def _session() -> Any:
    s = MagicMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_record_adds_audit_row_to_session() -> None:
    session = _session()
    repo = AuditRepository(session)
    row = await repo.record(
        actor_sub="alice",
        action="articles.created",
        resource_type="article",
        resource_id="my-slug",
        metadata={"access_level": "PUBLIC"},
    )
    assert isinstance(row, AuditLog)
    assert row.actor_sub == "alice"
    assert row.action == "articles.created"
    assert row.resource_type == "article"
    assert row.resource_id == "my-slug"
    assert row.audit_metadata == {"access_level": "PUBLIC"}
    session.add.assert_called_once_with(row)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_defaults_metadata_to_empty_dict() -> None:
    session = _session()
    repo = AuditRepository(session)
    row = await repo.record(
        actor_sub="alice",
        action="articles.archived",
        resource_type="article",
        resource_id="x",
    )
    assert row.audit_metadata == {}


@pytest.mark.asyncio
async def test_record_accepts_null_resource_id() -> None:
    """Некоторые системные events не привязаны к ресурсу."""
    session = _session()
    repo = AuditRepository(session)
    row = await repo.record(
        actor_sub="alice",
        action="system.startup",
        resource_type="system",
        resource_id=None,
        metadata={"version": "1.0"},
    )
    assert row.resource_id is None

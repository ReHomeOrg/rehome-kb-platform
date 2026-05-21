"""Unit-тесты WebhookRepository (E5.1 #87)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.webhooks.models import Webhook
from src.api.webhooks.repository import WebhookRepository, generate_secret


def _session_with(scalar: object = None, scalars_all: list[object] | None = None) -> Any:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    if scalars_all is not None:
        result.scalars.return_value.all.return_value = scalars_all
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    return session


def _make_webhook(client_id: str = "client-1") -> Webhook:
    w = Webhook()
    w.id = uuid4()
    w.client_id = client_id
    w.url = "https://example.com/hook"
    w.events = ["article.published"]
    w.secret = "x" * 32
    w.description = None
    w.created_at = datetime.now(UTC)
    w.last_delivery_at = None
    w.last_delivery_status = None
    w.deleted_at = None
    return w


def test_generate_secret_format() -> None:
    s = generate_secret()
    assert isinstance(s, str)
    assert len(s) >= 30  # token_urlsafe(32) → 43 chars


def test_generate_secret_uniqueness() -> None:
    secrets_set = {generate_secret() for _ in range(20)}
    assert len(secrets_set) == 20


@pytest.mark.asyncio
async def test_create_generates_secret_when_none() -> None:
    session = _session_with()
    repo = WebhookRepository(session)
    w = await repo.create(client_id="c", url="https://x/", events=["article.published"])
    assert w.secret is not None
    assert len(w.secret) >= 30
    session.add.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_uses_provided_secret() -> None:
    session = _session_with()
    repo = WebhookRepository(session)
    w = await repo.create(
        client_id="c",
        url="https://x/",
        events=["article.published"],
        secret="my-custom-secret",
    )
    assert w.secret == "my-custom-secret"


@pytest.mark.asyncio
@pytest.mark.security
async def test_get_by_id_and_owner_returns_webhook() -> None:
    wh = _make_webhook(client_id="alice")
    session = _session_with(scalar=wh)
    repo = WebhookRepository(session)
    result = await repo.get_by_id_and_owner(wh.id, "alice")
    assert result is wh


@pytest.mark.asyncio
@pytest.mark.security
async def test_get_by_id_and_owner_sql_includes_client_id() -> None:
    session = _session_with(scalar=None)
    repo = WebhookRepository(session)
    await repo.get_by_id_and_owner(uuid4(), "alice")
    sql = str(session.execute.call_args[0][0].compile()).lower()
    assert "client_id" in sql
    assert "deleted_at is null" in sql


@pytest.mark.asyncio
async def test_list_by_owner_sql_filters_client_and_alive() -> None:
    session = _session_with(scalars_all=[])
    repo = WebhookRepository(session)
    await repo.list_by_owner("alice")
    sql = str(session.execute.call_args[0][0].compile()).lower()
    assert "client_id" in sql
    assert "deleted_at is null" in sql
    assert "order by webhooks.created_at desc" in sql


@pytest.mark.asyncio
async def test_soft_delete_success_returns_true() -> None:
    wh = _make_webhook()
    session = _session_with(scalar=wh)
    repo = WebhookRepository(session)
    result = await repo.soft_delete(wh.id, wh.client_id)
    assert result is True
    assert wh.deleted_at is not None


@pytest.mark.asyncio
async def test_soft_delete_not_owned_returns_false() -> None:
    session = _session_with(scalar=None)
    repo = WebhookRepository(session)
    result = await repo.soft_delete(uuid4(), "wrong-owner")
    assert result is False


@pytest.mark.asyncio
async def test_soft_delete_idempotent() -> None:
    """Уже удалённый (deleted_at != null) → get_by_id_and_owner None → False."""

    session = _session_with(scalar=None)
    repo = WebhookRepository(session)
    result = await repo.soft_delete(uuid4(), "owner")
    assert result is False


# ---------------------------------------------------------------------------
# hard_delete_soft_deleted (#342, ФЗ-152 §21)


@pytest.mark.asyncio
async def test_hard_delete_soft_deleted_returns_rowcount() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=3))
    repo = WebhookRepository(session)
    n = await repo.hard_delete_soft_deleted(retention=timedelta(days=30))
    assert n == 3


@pytest.mark.asyncio
async def test_hard_delete_soft_deleted_zero_rowcount() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    repo = WebhookRepository(session)
    assert await repo.hard_delete_soft_deleted(retention=timedelta(days=30)) == 0


@pytest.mark.asyncio
async def test_hard_delete_soft_deleted_sql_targets_only_soft_deleted() -> None:
    """SQL должен filter'ить deleted_at IS NOT NULL AND deleted_at < cutoff
    — никогда не trigger'ит на live webhooks (deleted_at IS NULL)."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    repo = WebhookRepository(session)
    await repo.hard_delete_soft_deleted(retention=timedelta(days=30))
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()
    assert "delete from webhooks" in sql
    assert "deleted_at is not null" in sql


@pytest.mark.asyncio
async def test_hard_delete_soft_deleted_rowcount_none_returns_zero() -> None:
    """SQLAlchemy может вернуть rowcount=None; coalesce."""
    session = MagicMock()
    result = MagicMock()
    result.rowcount = None
    session.execute = AsyncMock(return_value=result)
    repo = WebhookRepository(session)
    assert await repo.hard_delete_soft_deleted(retention=timedelta(days=30)) == 0

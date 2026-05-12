"""Unit-тесты DocumentRepository (E2.8 #56).

Покрывает ADR-0003 invariants:
- SQL содержит `confidentiality IN (...)` на list И detail.
- Empty allowed_confidentialities → early return без SQL.
- Filters category/status/related_entity bind params.
- Cursor keyset через tuple_().
- list_filtered → has_more, slice limit.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.documents.models import Document
from src.api.documents.repository import DocumentRepository


@pytest.fixture
def empty_session() -> Any:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# ADR-0003 invariants on list


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_sql_includes_confidentiality_filter(
    empty_session: Any,
) -> None:
    repo = DocumentRepository(empty_session)
    await repo.list_filtered(frozenset({"PUBLIC", "INTERNAL"}))
    compiled = empty_session.execute.call_args[0][0].compile()
    sql = str(compiled).lower()
    params = compiled.params
    assert "confidentiality in" in sql
    bind = next(v for k, v in params.items() if k.startswith("confidentiality_"))
    assert set(bind) == {"PUBLIC", "INTERNAL"}


@pytest.mark.asyncio
async def test_list_empty_allowed_returns_empty_without_sql(
    empty_session: Any,
) -> None:
    """Защитный early-return при пустом маппинге."""
    repo = DocumentRepository(empty_session)
    rows, has_more = await repo.list_filtered(frozenset())
    assert rows == []
    assert has_more is False
    empty_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_list_category_filter_in_sql(empty_session: Any) -> None:
    repo = DocumentRepository(empty_session)
    await repo.list_filtered(frozenset({"PUBLIC"}), category="B")
    params = empty_session.execute.call_args[0][0].compile().params
    assert "B" in params.values()


@pytest.mark.asyncio
async def test_list_status_filter_in_sql(empty_session: Any) -> None:
    repo = DocumentRepository(empty_session)
    await repo.list_filtered(frozenset({"PUBLIC"}), status="ACTIVE")
    params = empty_session.execute.call_args[0][0].compile().params
    assert "ACTIVE" in params.values()


@pytest.mark.asyncio
async def test_list_related_entity_filter_in_sql(empty_session: Any) -> None:
    repo = DocumentRepository(empty_session)
    await repo.list_filtered(frozenset({"PUBLIC"}), related_entity="user:abc-123")
    params = empty_session.execute.call_args[0][0].compile().params
    assert "user:abc-123" in params.values()


@pytest.mark.asyncio
async def test_list_cursor_uses_row_value_comparison(
    empty_session: Any,
) -> None:
    repo = DocumentRepository(empty_session)
    cursor_dt = datetime(2026, 5, 12, 14, 0, tzinfo=UTC)
    cursor_id = uuid4()
    await repo.list_filtered(frozenset({"PUBLIC"}), cursor=(cursor_dt, cursor_id))
    sql = str(empty_session.execute.call_args[0][0].compile()).lower()
    # row-value comparison (updated_at, id) < (cursor.u, cursor.i)
    assert "updated_at" in sql
    assert " < " in sql
    # Не должен разваливаться в AND `updated_at < cu AND id < ci`
    assert "id < " not in sql.replace("documents.id", "")


@pytest.mark.asyncio
async def test_list_orders_by_updated_at_desc_id_desc(
    empty_session: Any,
) -> None:
    repo = DocumentRepository(empty_session)
    await repo.list_filtered(frozenset({"PUBLIC"}))
    sql = str(empty_session.execute.call_args[0][0].compile()).lower()
    assert "order by documents.updated_at desc" in sql
    assert "documents.id desc" in sql


@pytest.mark.asyncio
async def test_list_limit_plus_one_for_has_more(empty_session: Any) -> None:
    repo = DocumentRepository(empty_session)
    await repo.list_filtered(frozenset({"PUBLIC"}), limit=10)
    params = empty_session.execute.call_args[0][0].compile().params
    # limit+1 = 11
    assert 11 in params.values()


@pytest.mark.asyncio
async def test_list_has_more_true_when_extra_row_returned() -> None:
    """Если SQL вернул limit+1 строк — has_more=True, slice до limit."""
    docs = [_doc_with_id() for _ in range(11)]
    result = MagicMock()
    result.scalars.return_value.all.return_value = docs
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    repo = DocumentRepository(session)
    rows, has_more = await repo.list_filtered(frozenset({"PUBLIC"}), limit=10)
    assert has_more is True
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_list_has_more_false_when_fewer_rows() -> None:
    docs = [_doc_with_id() for _ in range(3)]
    result = MagicMock()
    result.scalars.return_value.all.return_value = docs
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    repo = DocumentRepository(session)
    rows, has_more = await repo.list_filtered(frozenset({"PUBLIC"}), limit=10)
    assert has_more is False
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# get_by_id


@pytest.mark.asyncio
@pytest.mark.security
async def test_get_by_id_sql_includes_confidentiality(empty_session: Any) -> None:
    repo = DocumentRepository(empty_session)
    await repo.get_by_id(uuid4(), frozenset({"PUBLIC"}))
    sql = str(empty_session.execute.call_args[0][0].compile()).lower()
    assert "confidentiality in" in sql


@pytest.mark.asyncio
async def test_get_by_id_empty_allowed_returns_none(empty_session: Any) -> None:
    repo = DocumentRepository(empty_session)
    result = await repo.get_by_id(uuid4(), frozenset())
    assert result is None
    empty_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_by_id_returns_document_when_found() -> None:
    doc = _doc_with_id()
    result = MagicMock()
    result.scalar_one_or_none.return_value = doc
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    repo = DocumentRepository(session)
    found = await repo.get_by_id(doc.id, frozenset({"PUBLIC"}))
    assert found is doc


def _doc_with_id() -> Document:
    d = Document()
    d.id = uuid4()
    d.title = "X"
    d.category = "A"
    d.version = None
    d.effective_from = None
    d.effective_to = None
    d.status = "ACTIVE"
    d.counterparty = None
    d.confidentiality = "PUBLIC"
    d.related_entity = None
    d.files = []
    d.signed_by = []
    d.audit_log = []
    d.created_at = datetime(2026, 5, 12, tzinfo=UTC)
    d.updated_at = datetime(2026, 5, 12, tzinfo=UTC)
    return d

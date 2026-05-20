"""Unit tests для create_document service helper (#327, ADR-0023 B)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.documents.models import Document
from src.api.documents.repository import DocumentRepository
from src.api.documents.service import create_document


def _make_doc() -> Document:
    d = Document()
    d.id = uuid4()
    d.title = "Договор аренды кв-001"
    d.category = "B"
    d.status = "DRAFT"
    d.confidentiality = "INTERNAL"
    d.version = "v1"
    d.counterparty = "ООО Партнёр"
    d.related_entity = "premises:abc-123"
    d.files = []
    d.signed_by = []
    d.audit_log = []
    d.created_at = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    d.updated_at = d.created_at
    return d


# ---------------------------------------------------------------------------
# Repository.create — pure storage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_create_rejects_invalid_category() -> None:
    repo = DocumentRepository(MagicMock())
    with pytest.raises(ValueError, match="Invalid category"):
        await repo.create(
            title="X",
            category="ZZ",
            status="DRAFT",
            confidentiality="INTERNAL",
        )


@pytest.mark.asyncio
async def test_repository_create_rejects_invalid_status() -> None:
    repo = DocumentRepository(MagicMock())
    with pytest.raises(ValueError, match="Invalid status"):
        await repo.create(
            title="X",
            category="A",
            status="WEIRD",
            confidentiality="INTERNAL",
        )


@pytest.mark.asyncio
async def test_repository_create_rejects_invalid_confidentiality() -> None:
    repo = DocumentRepository(MagicMock())
    with pytest.raises(ValueError, match="Invalid confidentiality"):
        await repo.create(
            title="X",
            category="A",
            status="DRAFT",
            confidentiality="TOP_SECRET",
        )


@pytest.mark.asyncio
async def test_repository_create_rejects_malformed_related_entity() -> None:
    repo = DocumentRepository(MagicMock())
    with pytest.raises(ValueError, match="Invalid related_entity"):
        await repo.create(
            title="X",
            category="A",
            status="DRAFT",
            confidentiality="PUBLIC",
            related_entity="contains spaces and & symbols",
        )


@pytest.mark.asyncio
async def test_repository_create_flushes_and_refreshes() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    repo = DocumentRepository(session)

    result = await repo.create(
        title="X",
        category="A",
        status="DRAFT",
        confidentiality="PUBLIC",
    )

    session.add.assert_called_once()
    added = session.add.call_args.args[0]
    assert added.title == "X"
    assert added.category == "A"
    assert added.status == "DRAFT"
    assert added.confidentiality == "PUBLIC"
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(added)
    assert result is added


# ---------------------------------------------------------------------------
# Service helper — audit + webhook orchestration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_document_emits_audit_and_webhook() -> None:
    doc = _make_doc()
    repo = MagicMock()
    repo.create = AsyncMock(return_value=doc)
    audit_repo = MagicMock()
    audit_repo.record = AsyncMock()
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=1)

    result = await create_document(
        repo=repo,
        audit_repo=audit_repo,
        dispatcher=dispatcher,
        actor_sub="admin-uuid",
        title=doc.title,
        category=doc.category,
        status=doc.status,
        confidentiality=doc.confidentiality,
        version=doc.version,
        counterparty=doc.counterparty,
        related_entity=doc.related_entity,
    )

    assert result is doc
    # Repository was called with все kwargs forwarded.
    repo.create.assert_awaited_once_with(
        title=doc.title,
        category=doc.category,
        status=doc.status,
        confidentiality=doc.confidentiality,
        version=doc.version,
        counterparty=doc.counterparty,
        related_entity=doc.related_entity,
    )
    # Audit row recorded.
    audit_repo.record.assert_awaited_once()
    audit_kwargs = audit_repo.record.call_args.kwargs
    assert audit_kwargs["action"] == "documents.created"
    assert audit_kwargs["resource_type"] == "document"
    assert audit_kwargs["resource_id"] == str(doc.id)
    assert audit_kwargs["actor_sub"] == "admin-uuid"
    # Metadata — machine-level, без title/counterparty (ADR-0023 / PII guard).
    assert audit_kwargs["metadata"] == {
        "category": "B",
        "status": "DRAFT",
        "confidentiality": "INTERNAL",
    }
    # Webhook dispatched. Payload — machine-level only (ADR-0023 B,
    # Architect 2026-05-20): `title` masked to avoid PII leak в external
    # subscribers.
    dispatcher.dispatch.assert_awaited_once()
    dispatch_kwargs = dispatcher.dispatch.call_args.kwargs
    assert dispatch_kwargs["event_type"] == "document.created"
    payload = dispatch_kwargs["payload"]
    assert payload["document_id"] == str(doc.id)
    assert "title" not in payload
    assert "counterparty" not in payload
    assert payload["category"] == "B"
    assert payload["status"] == "DRAFT"
    assert payload["confidentiality"] == "INTERNAL"
    assert payload["created_at"] == doc.created_at.isoformat()


@pytest.mark.asyncio
async def test_create_document_propagates_repository_validation_error() -> None:
    """Invalid input → ValueError from repo.create — service does NOT swallow."""
    repo = MagicMock()
    repo.create = AsyncMock(side_effect=ValueError("Invalid category: 'ZZ'"))
    audit_repo = MagicMock()
    audit_repo.record = AsyncMock()
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()

    with pytest.raises(ValueError, match="Invalid category"):
        await create_document(
            repo=repo,
            audit_repo=audit_repo,
            dispatcher=dispatcher,
            actor_sub="admin-uuid",
            title="X",
            category="ZZ",
            status="DRAFT",
            confidentiality="INTERNAL",
        )

    # Если create failed, audit + webhook не fire'ились.
    audit_repo.record.assert_not_awaited()
    dispatcher.dispatch.assert_not_awaited()

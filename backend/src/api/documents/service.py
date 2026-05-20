"""Document creation orchestration (#327, ADR-0023 B).

Per ADR-0023 Вариант B: POST /documents НЕ exposed на HTTP. Ingest
происходит через migration scripts / 1C integration / KYC providers —
все обязаны проходить через `create_document` чтобы:
- audit_log записывал каждое creation event с actor;
- webhook `document.created` fire'ил подписчиков (CS.8 gap closed).

Repository.create() остаётся pure storage; этот helper orchestrate'ит
side effects.

Webhook payload — machine-level only (Architect decision 2026-05-20):
`title` НЕ включается чтобы избежать leak в external subscribers,
которые могут быть вне trust boundary (e.g. 1C/CRM integrations
через partner systems). Subscriber retrieves full Document по `document_id`
через GET /documents/{id} с своим scope-фильтром.
"""

from __future__ import annotations

from src.api.audit.actions import ACTION_DOCUMENTS_CREATED, RESOURCE_DOCUMENT
from src.api.audit.repository import AuditRepository
from src.api.documents.models import Document
from src.api.documents.repository import DocumentRepository
from src.api.webhooks.dispatcher import WebhookEventDispatcher


async def create_document(
    *,
    repo: DocumentRepository,
    audit_repo: AuditRepository,
    dispatcher: WebhookEventDispatcher,
    actor_sub: str,
    title: str,
    category: str,
    status: str,
    confidentiality: str,
    version: str | None = None,
    counterparty: str | None = None,
    related_entity: str | None = None,
) -> Document:
    """Create document row + audit + dispatch `document.created` webhook.

    Caller's transaction owns the commit; this function только flush'ит
    через repo. Audit and dispatch happen post-flush (so document.id is
    available для payload), но до commit'а — поэтому если caller'ов
    transaction rollback'ится, audit/webhook rows тоже откатятся.
    """
    doc = await repo.create(
        title=title,
        category=category,
        status=status,
        confidentiality=confidentiality,
        version=version,
        counterparty=counterparty,
        related_entity=related_entity,
    )
    await audit_repo.record(
        actor_sub=actor_sub,
        action=ACTION_DOCUMENTS_CREATED,
        resource_type=RESOURCE_DOCUMENT,
        resource_id=str(doc.id),
        metadata={
            "category": doc.category,
            "status": doc.status,
            "confidentiality": doc.confidentiality,
        },
    )
    await dispatcher.dispatch(
        event_type="document.created",
        payload={
            "document_id": str(doc.id),
            "category": doc.category,
            "status": doc.status,
            "confidentiality": doc.confidentiality,
            "created_at": doc.created_at.isoformat(),
        },
    )
    return doc


__all__ = ["create_document"]

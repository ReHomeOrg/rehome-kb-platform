"""DocumentRepository — read-only метаданные документов с filter+cursor.

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: каждый SELECT по `documents` содержит
`WHERE confidentiality IN (:allowed)` — storage-level filter.

ADR-0008: Repository pattern обязателен. Router не работает с
AsyncSession напрямую.

#215 (ADR-0012 Phase B): добавлен `upsert_file` для multipart
upload — мутирует JSONB array `documents.files` атомарно с audit
row через caller's commit.

ADR-0023 B: добавлен `create()` как internal-only API для ingest paths
(migration scripts / 1C / KYC integration). HTTP surface остаётся
read-only — POST endpoint намеренно не exposed (см. ADR-0023). Caller
обычно вызывает через `documents.service.create_document` который
ferments audit + webhook trigger.
"""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import ColumnElement, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.documents.models import Document

# `related_entity` имеет формат `<type>:<identifier>` (например,
# `user:abc-123`, `premises:uuid`). Это произвольный текст без FK
# валидации в БД, но мы ограничиваем символы для anti-injection +
# sanity. allows alphanumerics, `-`, `_`, `.`, `:`.
RELATED_ENTITY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


class DocumentRepository:
    """Чтение documents с storage-level confidentiality фильтром."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_filtered(
        self,
        allowed_confidentialities: frozenset[str],
        *,
        category: str | None = None,
        status: str | None = None,
        related_entity: str | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 20,
    ) -> tuple[list[Document], bool]:
        """Возвращает страницу documents + флаг `has_more`.

        Фильтр (всегда): `confidentiality IN (:allowed)` — ADR-0003.
        Опциональные фильтры: category, status, related_entity.

        Если `allowed_confidentialities` пустой → возвращаем
        `([], False)` без SQL (`IN ()` в Postgres = false). Это
        отличается от articles (где пустой scope теоретически невозможен),
        тут — защита от misconfigured маппинга.

        Keyset pagination: `(updated_at, id) < (cursor.u, cursor.i)`
        через row-value comparison (паттерн из E2.2).
        """
        if not allowed_confidentialities:
            return [], False

        stmt = select(Document).where(Document.confidentiality.in_(list(allowed_confidentialities)))
        if category is not None:
            stmt = stmt.where(Document.category == category)
        if status is not None:
            stmt = stmt.where(Document.status == status)
        if related_entity is not None:
            stmt = stmt.where(Document.related_entity == related_entity)
        if cursor is not None:
            cursor_updated_at, cursor_id = cursor
            stmt = stmt.where(
                tuple_(Document.updated_at, Document.id)
                < tuple_(literal(cursor_updated_at), literal(cursor_id))
            )

        stmt = stmt.order_by(Document.updated_at.desc(), Document.id.desc()).limit(limit + 1)

        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def get_by_id(
        self,
        document_id: UUID,
        allowed_confidentialities: frozenset[str],
    ) -> Document | None:
        """Возвращает Document по id или None если scope не видит / нет.

        404-маск (ADR-0003): не различаем «нет документа» и «нет доступа».
        """
        if not allowed_confidentialities:
            return None
        clauses: list[ColumnElement[bool]] = [
            Document.id == document_id,
            Document.confidentiality.in_(list(allowed_confidentialities)),
        ]
        stmt = select(Document).where(*clauses).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        title: str,
        category: str,
        status: str,
        confidentiality: str,
        version: str | None = None,
        counterparty: str | None = None,
        related_entity: str | None = None,
    ) -> Document:
        """INSERT document. Storage-only — audit + webhook идут через
        `documents.service.create_document` (см. ADR-0023 B).

        Validates enum values against `Document.allowed_*` чтобы не
        зависеть от CHECK constraint round-trip'а (raises ValueError
        до flush'а — faster fail в migration scripts).
        """
        if category not in Document.allowed_categories():
            raise ValueError(f"Invalid category: {category!r}")
        if status not in Document.allowed_statuses():
            raise ValueError(f"Invalid status: {status!r}")
        if confidentiality not in Document.allowed_confidentialities():
            raise ValueError(f"Invalid confidentiality: {confidentiality!r}")
        if related_entity is not None and not RELATED_ENTITY_PATTERN.fullmatch(related_entity):
            raise ValueError(f"Invalid related_entity: {related_entity!r}")

        doc = Document(
            title=title,
            category=category,
            status=status,
            confidentiality=confidentiality,
            version=version,
            counterparty=counterparty,
            related_entity=related_entity,
        )
        self._session.add(doc)
        await self._session.flush()
        await self._session.refresh(doc)
        return doc

    async def upsert_file(
        self,
        document: Document,
        file_entry: dict[str, Any],
    ) -> Document:
        """Вставляет или заменяет entry в `documents.files` по `format`.

        Replace by format key — каждый формат уникален в files array.
        Мутирует in-place — caller отвечает за `await session.commit()`
        для atomicity с audit row.
        """
        # Replace existing entry с тем же format, либо append.
        file_format = file_entry["format"]
        new_files = [f for f in document.files if f.get("format") != file_format]
        new_files.append(file_entry)
        document.files = new_files
        # Mark column as mutated — SQLAlchemy ORM не detects изменения
        # внутри JSONB list automatically.
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(document, "files")
        await self._session.flush()
        return document


def get_document_repository(
    session: AsyncSession = Depends(get_session),
) -> DocumentRepository:
    """FastAPI Depends factory."""
    return DocumentRepository(session)

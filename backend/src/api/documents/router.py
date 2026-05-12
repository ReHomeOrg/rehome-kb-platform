"""FastAPI router для `/api/v1/documents/*` (E2.8 #56).

3 эндпоинта:
- `GET /documents` — список метаданных (DocumentMeta, без PII).
- `GET /documents/{id}` — detail (Document с signed_by + audit_log).
- `GET /documents/{id}/files/{format}` → 501 (download deferred до
  kb-files эпика; @architect approved в Issue #56).
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.auth.dependency import get_current_access_levels
from src.api.auth.scope import AccessLevel
from src.api.documents.access import compute_allowed_confidentialities
from src.api.documents.repository import (
    RELATED_ENTITY_PATTERN,
    DocumentRepository,
    get_document_repository,
)
from src.api.documents.schemas import (
    DocumentMeta,
    DocumentResponse,
    DocumentsListResponse,
    PaginationInfo,
)

router = APIRouter(prefix="/documents", tags=["Documents"])

LIMIT_MIN = 1
LIMIT_MAX = 100
LIMIT_DEFAULT = 20

Category = Literal["A", "B", "C", "D", "E", "F"]
Status = Literal["DRAFT", "ACTIVE", "EXPIRED", "CANCELLED"]
FileFormat = Literal["docx", "pdf", "html"]


@router.get(
    "",
    response_model=DocumentsListResponse,
    summary="Список документов",
)
async def list_documents(
    category: Category | None = Query(default=None),
    status: Status | None = Query(default=None),
    related_entity: str | None = Query(default=None, max_length=200),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=LIMIT_DEFAULT, ge=LIMIT_MIN, le=LIMIT_MAX),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentsListResponse:
    """`GET /api/v1/documents` — список метаданных с фильтрами.

    ADR-0003: scope маппится в confidentiality через
    `compute_allowed_confidentialities`. Outside-scope документы
    физически не возвращаются (фильтр на SQL-уровне).

    `signed_by` и `audit_log` в list НЕ возвращаются (только в detail).
    """
    allowed = compute_allowed_confidentialities(access_levels)

    if related_entity is not None and not RELATED_ENTITY_PATTERN.match(related_entity):
        raise HTTPException(
            status_code=422,
            detail="related_entity must match pattern <type>:<identifier>",
        )

    cursor_pair = decode_cursor(cursor) if cursor else None

    rows, has_more = await repo.list_filtered(
        allowed,
        category=category,
        status=status,
        related_entity=related_entity,
        cursor=cursor_pair,
        limit=limit,
    )

    cursor_next: str | None = None
    if has_more and rows:
        last = rows[-1]
        cursor_next = encode_cursor(last.updated_at, last.id)

    return DocumentsListResponse(
        data=[
            DocumentMeta(
                id=d.id,
                title=d.title,
                category=d.category,  # type: ignore[arg-type]
                version=d.version,
                effective_from=d.effective_from,
                effective_to=d.effective_to,
                status=d.status,  # type: ignore[arg-type]
                counterparty=d.counterparty,
                confidentiality=d.confidentiality,  # type: ignore[arg-type]
                related_entity=d.related_entity,
                files=d.files,  # type: ignore[arg-type]
            )
            for d in rows
        ],
        pagination=PaginationInfo(cursor_next=cursor_next, has_more=has_more),
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Метаданные документа",
)
async def get_document(
    document_id: UUID = Path(...),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentResponse:
    """`GET /api/v1/documents/{id}` — detail с signed_by + audit_log.

    404 (mask) если scope не видит ИЛИ id не существует.

    Доступ к detail подразумевает право видеть весь набор полей
    (signed_by, audit_log). Поэлементное маскирование — backlog
    ФЗ-152 enforcement эпика.
    """
    allowed = compute_allowed_confidentialities(access_levels)
    doc = await repo.get_by_id(document_id, allowed)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        category=doc.category,  # type: ignore[arg-type]
        version=doc.version,
        effective_from=doc.effective_from,
        effective_to=doc.effective_to,
        status=doc.status,  # type: ignore[arg-type]
        counterparty=doc.counterparty,
        confidentiality=doc.confidentiality,  # type: ignore[arg-type]
        related_entity=doc.related_entity,
        files=doc.files,  # type: ignore[arg-type]
        signed_by=doc.signed_by,  # type: ignore[arg-type]
        audit_log=doc.audit_log,  # type: ignore[arg-type]
    )


@router.get(
    "/{document_id}/files/{file_format}",
    summary="Скачать файл документа (NOT IMPLEMENTED)",
)
async def download_document_file(
    document_id: UUID = Path(...),  # noqa: ARG001
    file_format: FileFormat = Path(...),  # noqa: ARG001
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),  # noqa: ARG001
) -> None:
    """`GET /api/v1/documents/{id}/files/{format}` → 501.

    Architect approved deviation (Issue #56): полная реализация требует
    MinIO + signed URL — отдельный kb-files эпик. Возвращаем 501
    Not Implemented (стандартный HTTP-код для «эндпоинт известен, но
    не реализован»).
    """
    raise HTTPException(
        status_code=501,
        detail="Document file download is not yet implemented (kb-files epic, Issue #56)",
    )

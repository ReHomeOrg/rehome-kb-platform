"""FastAPI router для `/api/v1/documents/*` (E2.8 #56, ADR-0012 #214).

3 эндпоинта:
- `GET /documents` — список метаданных (DocumentMeta, без PII).
- `GET /documents/{id}` — detail (Document с signed_by + audit_log).
- `GET /documents/{id}/files/{format}` — 302 Redirect на presigned MinIO
  URL с TTL 5 минут (TZ §3.4). Audit log пишется на каждый download.
"""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.audit import (
    ACTION_DOCUMENTS_FILE_DOWNLOADED,
    RESOURCE_DOCUMENT,
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import get_current_access_levels, require_authenticated
from src.api.auth.scope import AccessLevel
from src.api.config import Settings, get_settings
from src.api.db import get_session
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
from src.api.documents.storage import (
    StorageError,
    StorageNotConfiguredError,
    presigned_get_url,
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


def _find_file(
    files: list[dict[str, Any]],
    file_format: str,
) -> dict[str, Any] | None:
    """Найти entry в `documents.files` JSONB array по format."""
    for f in files:
        if f.get("format") == file_format:
            return f
    return None


@router.get(
    "/{document_id}/files/{file_format}",
    summary="Скачать файл документа (302 → MinIO signed URL)",
    responses={
        302: {"description": "Redirect на временный signed URL MinIO (TTL 5 мин)"},
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Документ или формат не найден (anti-enumeration mask)"},
        502: {"description": "MinIO returned error"},
        503: {"description": "MinIO unreachable или не сконфигурирован"},
    },
)
async def download_document_file(
    document_id: UUID = Path(...),
    file_format: FileFormat = Path(...),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: DocumentRepository = Depends(get_document_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """`GET /api/v1/documents/{id}/files/{format}` → 302.

    Возвращает 302 Redirect на presigned MinIO URL с TTL 300s (TZ §3.4).
    Сначала ADR-0003 access_level check (scope must see document), затем
    JSONB lookup по format, затем audit_log row, затем signed URL.

    Анти-enumeration: 404 для (no access | document missing | format
    missing | files entry без storage_key). Backend не различает причины
    наружу — лог содержит детали.
    """
    allowed = compute_allowed_confidentialities(access_levels)
    doc = await repo.get_by_id(document_id, allowed)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    file_entry = _find_file(doc.files, file_format)
    if file_entry is None or not file_entry.get("storage_key"):
        # Format отсутствует ИЛИ legacy row без storage_key — 404 mask.
        raise HTTPException(status_code=404, detail="Document file not found")

    try:
        url = presigned_get_url(settings, file_entry["storage_key"])
    except StorageNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="Document storage не сконфигурирован",
        ) from None
    except StorageError as exc:
        status = 503 if exc.transient else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    # Audit на successful URL generation — пользователь физически ещё не
    # скачал (302 follow client-side), но intent зафиксирован.
    actor_sub = str(_claims.get("sub", "unknown"))
    await audit.record(
        actor_sub=actor_sub,
        action=ACTION_DOCUMENTS_FILE_DOWNLOADED,
        resource_type=RESOURCE_DOCUMENT,
        resource_id=str(document_id),
        metadata={"format": file_format, "size_bytes": file_entry.get("size_bytes")},
    )
    await session.commit()

    return RedirectResponse(url=url, status_code=302)

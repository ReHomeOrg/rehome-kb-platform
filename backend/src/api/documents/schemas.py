"""Pydantic схемы для `/api/v1/documents` (E2.8 #56).

OpenAPI 04:
- `DocumentMeta` — для list (без signed_by/audit_log)
- `Document` = DocumentMeta + signed_by + audit_log (для detail)
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Category = Literal["A", "B", "C", "D", "E", "F"]
Status = Literal["DRAFT", "ACTIVE", "EXPIRED", "CANCELLED"]
Confidentiality = Literal["PUBLIC", "INTERNAL", "RESTRICTED"]
FileFormat = Literal["docx", "pdf", "html"]


class DocumentFile(BaseModel):
    """Один файл документа (метаданные без download URL).

    Источник scheme — OpenAPI Document.files item.
    """

    format: FileFormat
    size_bytes: int = Field(ge=0)
    sha256: str


class SignedBy(BaseModel):
    """Подписант документа. ФИО — ПДн (возвращается только в detail)."""

    role: str
    name: str
    date: datetime
    method: Literal["sms_otp", "qep", "paper"]


class AuditLogEntry(BaseModel):
    """Запись audit_log документа. actor — Keycloak `sub` (UUID) или
    идентификатор. ПДн уровня identifier — возвращается только в detail.

    Полноценное маскирование (например, agent видит только count) —
    backlog ФЗ-152 enforcement эпика.
    """

    actor: str
    action: str
    ts: datetime


class DocumentMeta(BaseModel):
    """Метаданные документа без signed_by/audit_log — для list.

    `id` exposes как UUID — это OpenAPI требование (отличие от
    categories, где id скрыто и slug-based addressing).
    """

    id: UUID
    title: str
    category: Category
    version: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: Status
    counterparty: str | None = None
    confidentiality: Confidentiality
    related_entity: str | None = None
    files: list[DocumentFile] = Field(default_factory=list)


class DocumentResponse(DocumentMeta):
    """Detail-response = DocumentMeta + signed_by + audit_log."""

    signed_by: list[SignedBy] = Field(default_factory=list)
    audit_log: list[AuditLogEntry] = Field(default_factory=list)


class DocumentsListResponse(BaseModel):
    """Ответ для `GET /api/v1/documents`."""

    data: list[DocumentMeta]
    pagination: "PaginationInfo"


class PaginationInfo(BaseModel):
    """Курсорная пагинация (E2.2 паттерн)."""

    cursor_next: str | None = None
    has_more: bool = False


DocumentsListResponse.model_rebuild()

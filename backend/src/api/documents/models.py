"""SQLAlchemy ORM модель Document (E2.8 #56).

Соответствует OpenAPI 04 `Document` schema. Все enum-поля имеют CHECK
constraints на стороне БД (defence-in-depth) — синхронизация enum-
значений с приложением проверяется тестом `test_models_check_sync.py`.

`files`, `signed_by`, `audit_log` — JSONB arrays. signed_by и audit_log
содержат ПДн (ФИО, actor ID) и возвращаются ТОЛЬКО в detail-response
(`GET /documents/{id}`), не в list.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class Document(Base):
    """Юридический документ kb-files (Issue #56).

    ВАЖНО (ADR-0003 для documents):
    - `confidentiality IN (...)` фильтр обязателен на всех SELECT.
    - 404 (не 403) при out-of-scope (mask существования).
    """

    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    version: Mapped[str | None] = mapped_column(String(50))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    counterparty: Mapped[str | None] = mapped_column(Text)
    confidentiality: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
    )
    related_entity: Mapped[str | None] = mapped_column(String(200), index=True)

    files: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    signed_by: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    audit_log: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('A', 'B', 'C', 'D', 'E', 'F')",
            name="ck_documents_category",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'EXPIRED', 'CANCELLED')",
            name="ck_documents_status",
        ),
        CheckConstraint(
            "confidentiality IN ('PUBLIC', 'INTERNAL', 'RESTRICTED')",
            name="ck_documents_confidentiality",
        ),
        # Композитный индекс: типичный list-запрос фильтрует по
        # confidentiality, status и сортирует по updated_at.
        Index(
            "ix_documents_conf_status_updated",
            "confidentiality",
            "status",
            "updated_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return f"<Document id={self.id!r} title={self.title!r} conf={self.confidentiality!r}>"

    # Источник истины enum-значений (sync с CHECK constraints выше).
    @staticmethod
    def allowed_categories() -> tuple[str, ...]:
        return ("A", "B", "C", "D", "E", "F")

    @staticmethod
    def allowed_statuses() -> tuple[str, ...]:
        return ("DRAFT", "ACTIVE", "EXPIRED", "CANCELLED")

    @staticmethod
    def allowed_confidentialities() -> tuple[str, ...]:
        return ("PUBLIC", "INTERNAL", "RESTRICTED")

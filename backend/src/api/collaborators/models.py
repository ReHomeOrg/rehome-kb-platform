"""SQLAlchemy Collaborator model (ADR-0014, ТЗ §10).

CHECK constraints в БД (migration 0019) — defence-in-depth. Drift
тест (`test_collaborators_check_sync.py`) verify'ит синхронизацию
enum'ов между migration + access.py + OpenAPI yaml.

JSONB поля (`contacts`, `financial_terms`, `api_integration`, `sla`,
`counterparty_check`, `audit_log`) — структура валидируется Pydantic
на API boundary (ADR-0014 §4 — DB CHECK на JSONB shape — overengineering).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class Collaborator(Base):
    """Внешний исполнитель платформы (ТЗ §10).

    ВАЖНО (ADR-0014 §3):
    - `financial_group IN (...)` фильтр обязателен на всех SELECT.
    - 404 mask при out-of-scope (anti-enumeration, ADR-0003 pattern).
    - 3 response Pydantic schemas (Public/Internal/Admin) для per-field
      ПДн masking.

    Invariant (ADR-0014 §2): pair (type, financial_group) jёстко
    закреплён ТЗ §10.3, кроме `type='other'` (любая группа). Enforced
    через CHECK constraint в migration 0019.
    """

    __tablename__ = "collaborators"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    financial_group: Mapped[str] = mapped_column(String(1), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    legal_entity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ogrn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kpp: Mapped[str | None] = mapped_column(String(20), nullable=True)

    service_area: Mapped[str] = mapped_column(String(500), nullable=False)
    working_hours: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    responsible_internal: Mapped[str | None] = mapped_column(String(200), nullable=True)

    contract_document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    fallback_collaborator_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    rating: Mapped[Decimal | None] = mapped_column(Numeric(precision=3, scale=2), nullable=True)

    contacts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    financial_terms: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    api_integration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    sla: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    counterparty_check: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    audit_log: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # Slice 3 (ADR-0015) — portal access tier + onboarding metadata.
    portal_access_level: Mapped[str] = mapped_column(
        String(10), nullable=False, default="NONE", server_default="NONE"
    )
    portal_access_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    onboarding_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="staff_invite", server_default="staff_invite"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

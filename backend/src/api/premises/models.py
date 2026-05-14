"""SQLAlchemy ORM модель PremisesCard (#142, PZ §5).

Foundation для модуля premises_cards. Storage-level access control:
- Status filter (DRAFT / ARCHIVED видны только STAFF).
- Per-block visibility — application-level через `project_for_scope`.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class PremisesCard(Base):
    """Карточка сдаваемой квартиры (PZ §5).

    Блоки данных:
    - §5.1 Идентификация: address / cadastral / status — typed columns;
      owner / owner_representative / current_tenant — JSONB blocks с
      ПДн (требуют STAFF-уровня видимости в Stage 1).
    - §5.2 Финансы — `financial_data` JSONB.
    - §5.3 Информация для жильца — `tenant_info` JSONB.
    - §5.4 Внутренние данные — `internal_data` JSONB (STAFF only).

    Per-tenant / per-owner access — Stage 2 (после Users / Contracts
    модулей). В Stage 1 — простая модель: identification public-ish,
    остальное STAFF.
    """

    __tablename__ = "premises_cards"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    internal_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="DRAFT")
    premises_uuid: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cadastral_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    owner: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    owner_representative: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    current_tenant: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    financial_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    tenant_info: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    internal_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    extra_identification: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'RENTED', 'ARCHIVED')",
            name="ck_premises_cards_status",
        ),
        CheckConstraint(
            "char_length(slug) BETWEEN 1 AND 200",
            name="ck_premises_cards_slug_length",
        ),
        Index("ix_premises_cards_status", "status"),
        Index("ix_premises_cards_cadastral_number", "cadastral_number"),
        Index("ix_premises_cards_address_trgm", "address"),
    )

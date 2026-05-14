"""Pydantic schemas для PremisesCard (#142, PZ §5).

`PremisesView` — projection-based response: поля, недоступные scope'у
caller'а, omit'ятся из output. `project_for_scope` принимает ORM-row +
access_levels → возвращает фильтрованный dict, который Pydantic
валидирует в `PremisesView`.

ACCESS RULES (Stage 1):
- PUBLIC fields: slug, status, address, postal_code, cadastral_number,
  extra_identification (содержит neutral facts типа площади, этажа).
- STAFF-only fields: owner, owner_representative, current_tenant,
  internal_code, premises_uuid, financial_data, tenant_info,
  internal_data.

Per-tenant access (наниматель видит tenant_info) и per-owner access
(собственник видит financial_data) — Stage 2 после Users / Contracts.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.auth.scope import AccessLevel
from src.api.premises.models import PremisesCard

# Slug pattern идентичен articles (lowercase ASCII + цифры + дефисы).
SLUG_PATTERN = r"^[a-z0-9-]+$"

PremisesStatus = Literal["DRAFT", "PUBLISHED", "RENTED", "ARCHIVED"]


class PremisesView(BaseModel):
    """Projection-based response. Опциональные поля = STAFF-only blocks.

    Pydantic `model_config(extra='ignore')` устойчив к extra полям
    из ORM сериализации (которые не должны попасть в response).
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    # Always-visible (с учётом status filter в repository).
    id: UUID
    slug: str
    status: str
    address: str
    postal_code: str | None = None
    cadastral_number: str | None = None
    extra_identification: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    # STAFF-only blocks (omitted в non-STAFF responses).
    internal_code: str | None = None
    premises_uuid: UUID | None = None
    owner: dict[str, Any] | None = None
    owner_representative: dict[str, Any] | None = None
    current_tenant: dict[str, Any] | None = None
    financial_data: dict[str, Any] | None = None
    tenant_info: dict[str, Any] | None = None
    internal_data: dict[str, Any] | None = None


class PremisesSearchHit(BaseModel):
    """FTS search result hit — identification subset + relevance score."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    slug: str
    address: str
    postal_code: str | None = None
    cadastral_number: str | None = None
    status: str
    score: float = Field(ge=0)


class PremisesSearchResponse(BaseModel):
    """`POST /premises-cards/search` — список hits, no pagination
    (top-N только, follow-up cursor если нужно)."""

    data: list[PremisesSearchHit]


class PremisesSearchInput(BaseModel):
    """Body для POST /premises-cards/search."""

    model_config = ConfigDict(extra="forbid")

    q: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)


class PremisesSummary(BaseModel):
    """Краткая карточка для list endpoint (без JSONB blocks).

    Только identification fields, видимые всем. ПДн blocks никогда
    не возвращаются в list (даже для STAFF — staff-инспектор делает
    detail-запрос для каждой карточки).
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    slug: str
    status: str
    address: str
    postal_code: str | None = None
    cadastral_number: str | None = None
    updated_at: datetime


class PaginationInfo(BaseModel):
    cursor_next: str | None = None
    has_more: bool = False


class PremisesListResponse(BaseModel):
    data: list[PremisesSummary]
    pagination: PaginationInfo


def _is_staff(access_levels: frozenset[AccessLevel]) -> bool:
    """Простой test'ер: STAFF-уровень дан хотя бы одной staff-ролью.

    `AccessLevel.STAFF` / `LEGAL` / `HR_RESTRICTED` — все они staff-tier
    в ADR-0003. Любой из них даёт право видеть PII blocks.
    """
    staff_levels = {AccessLevel.STAFF, AccessLevel.LEGAL, AccessLevel.HR_RESTRICTED}
    return bool(access_levels & staff_levels)


def project_for_scope(
    card: PremisesCard,
    access_levels: frozenset[AccessLevel],
) -> PremisesView:
    """Build `PremisesView` projection per access_levels.

    Non-STAFF callers получают только identification subset; STAFF
    видят все blocks. Это Stage 1 модель — finer-grained access
    (наниматель видит tenant_info etc.) — после Users / Contracts.
    """
    base: dict[str, Any] = {
        "id": card.id,
        "slug": card.slug,
        "status": card.status,
        "address": card.address,
        "postal_code": card.postal_code,
        "cadastral_number": card.cadastral_number,
        "extra_identification": card.extra_identification,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }
    if _is_staff(access_levels):
        base.update(
            internal_code=card.internal_code,
            premises_uuid=card.premises_uuid,
            owner=card.owner,
            owner_representative=card.owner_representative,
            current_tenant=card.current_tenant,
            financial_data=card.financial_data,
            tenant_info=card.tenant_info,
            internal_data=card.internal_data,
        )
    return PremisesView.model_validate(base)


# ---------------------------------------------------------------------------
# Write-side schemas (#148, PZ §5)


class PremisesInput(BaseModel):
    """Body для POST /premises-cards — full create.

    `slug` — caller-provided (не auto-derived от address, т.к. адреса
    могут быть длинные / non-ASCII). Pattern enforced на router'е.
    `status` default DRAFT — explicit lifecycle.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=200, pattern=SLUG_PATTERN)
    internal_code: str | None = Field(default=None, max_length=64)
    status: PremisesStatus = "DRAFT"
    premises_uuid: UUID | None = None
    address: str = Field(min_length=1, max_length=500)
    postal_code: str | None = Field(default=None, max_length=16)
    cadastral_number: str | None = Field(default=None, max_length=64)
    owner: dict[str, Any] = Field(default_factory=dict)
    owner_representative: dict[str, Any] | None = None
    current_tenant: dict[str, Any] | None = None
    financial_data: dict[str, Any] = Field(default_factory=dict)
    tenant_info: dict[str, Any] = Field(default_factory=dict)
    internal_data: dict[str, Any] = Field(default_factory=dict)
    extra_identification: dict[str, Any] = Field(default_factory=dict)


class PremisesPatch(BaseModel):
    """Body для PATCH /premises-cards/{slug} — partial update.

    Все fields optional; только non-None попадают в patch dict. Status
    transitions произвольные (DRAFT → ARCHIVED через PATCH допустим;
    archive endpoint — convenience wrapper).
    """

    model_config = ConfigDict(extra="forbid")

    internal_code: str | None = Field(default=None, max_length=64)
    status: PremisesStatus | None = None
    premises_uuid: UUID | None = None
    address: str | None = Field(default=None, min_length=1, max_length=500)
    postal_code: str | None = Field(default=None, max_length=16)
    cadastral_number: str | None = Field(default=None, max_length=64)
    owner: dict[str, Any] | None = None
    owner_representative: dict[str, Any] | None = None
    current_tenant: dict[str, Any] | None = None
    financial_data: dict[str, Any] | None = None
    tenant_info: dict[str, Any] | None = None
    internal_data: dict[str, Any] | None = None
    extra_identification: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def _v_status(cls, v: PremisesStatus | None) -> PremisesStatus | None:
        # Literal enforce'ит — null passthrough.
        return v

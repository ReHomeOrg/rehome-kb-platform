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
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.api.auth.scope import AccessLevel
from src.api.premises.models import PremisesCard


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

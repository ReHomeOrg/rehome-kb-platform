"""Pydantic schemas для Collaborators API (ADR-0014 §7).

3 response variants для per-field ПДн masking:
- `CollaboratorPublic` — для guest/LOGGED/AGENT (видят только D-группу,
  без юр.реквизитов / financial_terms / person_name контактов)
- `CollaboratorInternal` — для STAFF/LEGAL (всё кроме `audit_log`)
- `CollaboratorAdmin` — для staff_admin (всё включая audit_log)

Request schemas:
- `CollaboratorCreate` — POST body. financial_group авто-derive из type
  (кроме 'other').
- `CollaboratorPatch` — PATCH body, все поля optional.

ContactEntry — структура одного элемента в `contacts` JSONB array.
`person_name` — ПДн → отдельная схема CollaboratorPublic исключает её.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.api.collaborators.access import (
    COLLABORATOR_TYPES,
    FINANCIAL_GROUPS,
    LEGAL_ENTITY_TYPES,
    STATUSES,
    TYPE_TO_FINANCIAL_GROUP,
    derive_financial_group,
)

# Literal'ы — sync с access.py (drift тест test_models_check_sync).
CollaboratorType = Literal[
    "management_company",
    "emergency_service",
    "repair_handyman",
    "cleaning",
    "moving",
    "key_delivery",
    "insurance",
    "payment_partner",
    "kyc_provider",
    "edo_provider",
    "sms_voice",
    "it_infrastructure",
    "legal_consultant",
    "other",
]
FinancialGroup = Literal["A", "B", "C", "D"]
CollaboratorStatus = Literal["DRAFT", "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "ARCHIVED"]
LegalEntityType = Literal["individual", "self_employed", "ip", "legal_entity"]
PortalAccessLevel = Literal["NONE", "LIGHT", "FULL"]
OnboardingSource = Literal["form", "staff_invite", "api", "migration"]


class ContactEntry(BaseModel):
    """Один контакт в `contacts` JSONB array (ТЗ §10.5)."""

    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    messenger: str | None = Field(default=None, max_length=200)
    emergency_channel: bool = False
    person_name: str | None = Field(default=None, max_length=200)  # ПДн!
    person_role: str | None = Field(default=None, max_length=100)


# ---------------------------------------------------------------------------
# Response schemas — 3 уровня (ADR-0014 §7)


class CollaboratorPublic(BaseModel):
    """Публичный view (guest/LOGGED/AGENT). Только D-группа коллаборантов,
    БЕЗ юр.реквизитов / financial_terms / person_name контактов."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: CollaboratorType
    brand_name: str | None
    financial_group: FinancialGroup
    status: CollaboratorStatus
    service_area: str
    working_hours: str | None
    website: str | None
    rating: Decimal | None
    # `contacts` без person_name/person_role — отдельная схема ContactPublic
    # был бы over-engineering. Серверный код фильтрует поля при serialization.


class CollaboratorInternal(CollaboratorPublic):
    """STAFF view — расширяет публичный юр.данными и SLA/financial_terms.
    Не включает audit_log (только staff_admin)."""

    name: str  # юр.название
    legal_entity_type: LegalEntityType | None
    inn: str | None
    ogrn: str | None
    kpp: str | None
    responsible_internal: str | None
    contract_document_id: UUID | None
    fallback_collaborator_id: UUID | None
    contacts: list[ContactEntry]
    financial_terms: dict[str, Any]
    api_integration: dict[str, Any]
    sla: dict[str, Any]
    counterparty_check: dict[str, Any]
    onboarding_source: OnboardingSource
    created_at: datetime
    updated_at: datetime


class CollaboratorAdmin(CollaboratorInternal):
    """staff_admin view — добавляет audit_log."""

    audit_log: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Request schemas


class CollaboratorCreate(BaseModel):
    """POST /collaborators body.

    `financial_group` опциональна:
    - для type ≠ 'other' — auto-derive из TYPE_TO_FINANCIAL_GROUP map
    - для type == 'other' — ОБЯЗАТЕЛЬНО указать explicitly
    """

    name: str = Field(min_length=1, max_length=500)
    brand_name: str | None = Field(default=None, max_length=200)
    type: CollaboratorType
    financial_group: FinancialGroup | None = None
    status: CollaboratorStatus = "DRAFT"
    legal_entity_type: LegalEntityType | None = None
    inn: str | None = Field(default=None, max_length=20)
    ogrn: str | None = Field(default=None, max_length=20)
    kpp: str | None = Field(default=None, max_length=20)
    service_area: str = Field(min_length=1, max_length=500)
    working_hours: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    responsible_internal: str | None = Field(default=None, max_length=200)
    contract_document_id: UUID | None = None
    fallback_collaborator_id: UUID | None = None
    contacts: list[ContactEntry] = Field(default_factory=list)
    financial_terms: dict[str, Any] = Field(default_factory=dict)
    api_integration: dict[str, Any] = Field(default_factory=dict)
    sla: dict[str, Any] = Field(default_factory=dict)
    counterparty_check: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def resolve_financial_group(self) -> CollaboratorCreate:
        """Auto-derive financial_group для известных типов; validate
        invariant для explicit."""
        if self.financial_group is None:
            try:
                # type-checker happy: derive raise'ит для 'other'
                self.financial_group = derive_financial_group(self.type)  # type: ignore[assignment]
            except ValueError as exc:
                raise ValueError(
                    f"financial_group обязательно для type='{self.type}' " f"(see ADR-0014 §2)"
                ) from exc
        else:
            # Validate invariant: explicit group должна совпадать с derived
            # (кроме 'other').
            if self.type != "other":
                expected = TYPE_TO_FINANCIAL_GROUP[self.type]
                if self.financial_group != expected:
                    raise ValueError(
                        f"type='{self.type}' закреплён за financial_group='{expected}', "
                        f"got '{self.financial_group}' (ТЗ §10.3 + ADR-0014 §2)"
                    )
        return self


class SuspendRequest(BaseModel):
    """POST /collaborators/{id}/suspend body (ТЗ §3.10.2)."""

    reason: str = Field(min_length=1, max_length=500)
    until: str | None = Field(
        default=None,
        max_length=20,
        description="ISO-8601 дата восстановления (опционально). Caller-managed; "
        "не enforced на стороне БД в Slice 2.",
    )


class OnboardingRequest(BaseModel):
    """POST /collaborators/onboarding body (ADR-0015 §6, ТЗ §10.8).

    Public endpoint без auth — payload минимальный, staff'у всё равно
    проверять Dadata + activation. `type='other'` запрещён через
    self-form (требует staff_invite per ADR-0015 §6).
    """

    name: str = Field(min_length=2, max_length=500)
    brand_name: str | None = Field(default=None, max_length=200)
    type: CollaboratorType
    legal_entity_type: LegalEntityType | None = None
    inn: str | None = Field(
        default=None,
        pattern=r"^\d{10}$|^\d{12}$",
        description="ИНН (10 цифр юрлицо, 12 цифр ИП/физлицо).",
    )
    service_area: str = Field(min_length=3, max_length=500)
    contact: ContactEntry
    portal_access_level_requested: PortalAccessLevel = Field(
        default="LIGHT",
        description=(
            "Желаемый tier кабинета. Staff может override при activation "
            "(ТЗ §10.8.1). NONE / LIGHT / FULL — описание в ТЗ §10.8."
        ),
    )
    message: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_self_form_constraints(self) -> OnboardingRequest:
        """ADR-0015 §6: self-form запрещает 'other' (требует staff review)."""
        if self.type == "other":
            raise ValueError(
                "type='other' требует staff_invite (POST /collaborators), "
                "не self-form (ADR-0015 §6)"
            )
        # ContactEntry — хотя бы один из phone/email/messenger обязателен.
        c = self.contact
        if not (c.phone or c.email or c.messenger):
            raise ValueError("contact должен содержать хотя бы один из phone/email/messenger")
        return self


class OnboardingResponse(BaseModel):
    """ADR-0015 §6: anti-enumeration response — только id+status+message."""

    id: UUID
    status: CollaboratorStatus
    message: str


class PremisesCollaboratorAssignment(BaseModel):
    """POST /premises/{id}/collaborators body (ТЗ §10.6, Slice 5)."""

    collaborator_id: UUID
    role: str = Field(
        min_length=1,
        max_length=50,
        description="Назначение, e.g. 'default_uk', 'emergency_water', 'plumber'. "
        "Freeform — slice 5 без enum (ТЗ §10.6 только примеры).",
    )
    priority: int = Field(default=1, ge=1, le=99)
    notes: str | None = Field(default=None, max_length=2000)


class PremisesCollaboratorRow(BaseModel):
    """Один row в GET /premises/{id}/collaborators response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    collaborator_id: UUID
    role: str
    priority: int
    notes: str | None
    assigned_at: datetime
    assigned_by: str
    # Inline-developed collaborator card (Public variant: безопасно для guest).
    collaborator: CollaboratorPublic


class PremisesCollaboratorsListResponse(BaseModel):
    data: list[PremisesCollaboratorRow]


class PortalAccessChangeRequest(BaseModel):
    """PUT /collaborators/{id}/portal-access body (ADR-0015 §5)."""

    portal_access_level: PortalAccessLevel
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Required для повышения tier'а (ТЗ §10.8.1), optional для понижения.",
    )


class CollaboratorPatch(BaseModel):
    """PATCH body — все поля optional. NB: `type` и `financial_group`
    можно менять, но проверяем invariant (как в Create).

    Status можно менять в любую сторону — transition validation в
    Slice 2 (/activate, /suspend endpoints).
    """

    name: str | None = Field(default=None, min_length=1, max_length=500)
    brand_name: str | None = Field(default=None, max_length=200)
    type: CollaboratorType | None = None
    financial_group: FinancialGroup | None = None
    status: CollaboratorStatus | None = None
    legal_entity_type: LegalEntityType | None = None
    inn: str | None = Field(default=None, max_length=20)
    ogrn: str | None = Field(default=None, max_length=20)
    kpp: str | None = Field(default=None, max_length=20)
    service_area: str | None = Field(default=None, min_length=1, max_length=500)
    working_hours: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    responsible_internal: str | None = Field(default=None, max_length=200)
    contract_document_id: UUID | None = None
    fallback_collaborator_id: UUID | None = None
    contacts: list[ContactEntry] | None = None
    financial_terms: dict[str, Any] | None = None
    api_integration: dict[str, Any] | None = None
    sla: dict[str, Any] | None = None
    counterparty_check: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_type_group_invariant(self) -> CollaboratorPatch:
        """Если оба type и financial_group присутствуют — invariant check."""
        if self.type is not None and self.type != "other" and self.financial_group is not None:
            expected = TYPE_TO_FINANCIAL_GROUP[self.type]
            if self.financial_group != expected:
                raise ValueError(f"type='{self.type}' требует financial_group='{expected}'")
        return self


# ---------------------------------------------------------------------------
# Pagination response


class PaginationInfo(BaseModel):
    cursor_next: str | None
    has_more: bool


class CollaboratorsListResponse(BaseModel):
    """List response — meta-объекты (тот же variant что и detail's публичная
    часть)."""

    data: list[CollaboratorPublic | CollaboratorInternal]
    pagination: PaginationInfo


__all__ = [
    "COLLABORATOR_TYPES",
    "FINANCIAL_GROUPS",
    "LEGAL_ENTITY_TYPES",
    "STATUSES",
    "CollaboratorAdmin",
    "CollaboratorCreate",
    "CollaboratorInternal",
    "CollaboratorPatch",
    "CollaboratorPublic",
    "CollaboratorStatus",
    "CollaboratorType",
    "CollaboratorsListResponse",
    "ContactEntry",
    "FinancialGroup",
    "LegalEntityType",
    "OnboardingRequest",
    "OnboardingResponse",
    "OnboardingSource",
    "PaginationInfo",
    "PortalAccessChangeRequest",
    "PortalAccessLevel",
    "PremisesCollaboratorAssignment",
    "PremisesCollaboratorRow",
    "PremisesCollaboratorsListResponse",
    "SuspendRequest",
]

"""Collaborators access mapping — ADR-0014 §3 (scope → visible financial groups).

Источник истины для:
- Списка 14 типов коллаборантов (ТЗ §10.2)
- Списка 4 финансовых групп (ТЗ §10.3)
- Списка 5 статусов (ТЗ §10.5)
- Invariant (type, financial_group) — для derive_financial_group + ADR-0014 §2

Drift тест (`test_collaborators_check_sync.py`) verify'ит соответствие с
migration CHECK constraints + OpenAPI yaml enums.
"""

from __future__ import annotations

from typing import Final

from src.api.auth.scope import AccessLevel

# ТЗ §10.2 — 14 типов. Любая правка — синхронно в migration + OpenAPI.
COLLABORATOR_TYPES: Final[tuple[str, ...]] = (
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
)

# ТЗ §10.3 — 4 финансовые группы.
FINANCIAL_GROUPS: Final[tuple[str, ...]] = ("A", "B", "C", "D")

# ТЗ §10.5 — 5 статусов lifecycle.
STATUSES: Final[tuple[str, ...]] = (
    "DRAFT",
    "PENDING_REVIEW",
    "ACTIVE",
    "SUSPENDED",
    "ARCHIVED",
)

# ТЗ §10.5 — типы юр.лиц.
LEGAL_ENTITY_TYPES: Final[tuple[str, ...]] = (
    "individual",
    "self_employed",
    "ip",
    "legal_entity",
)

# ТЗ §10.8 — уровни кабинета коллаборанта (Slice 3, ADR-0015).
PORTAL_ACCESS_LEVELS: Final[tuple[str, ...]] = ("NONE", "LIGHT", "FULL")

# ADR-0015 §4 — как коллаборант появился в системе.
ONBOARDING_SOURCES: Final[tuple[str, ...]] = (
    "form",  # self-form через /onboarding
    "staff_invite",  # staff создал через POST /collaborators
    "api",  # automated bulk import
    "migration",  # backfilled from legacy
)

# ТЗ §10.3 invariant: pair (type, financial_group). 'other' — wildcard
# (не в map'е, поэтому derive_financial_group raise'ит ValueError).
TYPE_TO_FINANCIAL_GROUP: Final[dict[str, str]] = {
    "payment_partner": "A",
    "kyc_provider": "A",
    "sms_voice": "A",
    "it_infrastructure": "A",
    "edo_provider": "A",
    "legal_consultant": "A",
    "cleaning": "B",
    "moving": "B",
    "key_delivery": "B",
    "repair_handyman": "B",
    "insurance": "C",
    "management_company": "D",
    "emergency_service": "D",
}


def derive_financial_group(collaborator_type: str) -> str:
    """Vозвращает invariant'ную финансовую группу для типа.

    Для `type='other'` — raise ValueError, caller обязан указать группу
    явно (ТЗ §10.3: "Финансовая группа выбирается при заведении,
    требует ADR").

    Raises:
        ValueError: для `type='other'` ИЛИ unknown type'а.
    """
    if collaborator_type == "other":
        raise ValueError(
            "type='other' требует явно указать financial_group " "(ТЗ §10.3 + ADR-0014 §2)"
        )
    if collaborator_type not in TYPE_TO_FINANCIAL_GROUP:
        raise ValueError(f"Unknown collaborator type: {collaborator_type!r}")
    return TYPE_TO_FINANCIAL_GROUP[collaborator_type]


def compute_visible_groups(access_levels: frozenset[AccessLevel]) -> frozenset[str]:
    """Возвращает financial groups, видимые scope'у.

    ADR-0014 §3:
    - guest / PUBLIC только → {'D'} (управляющие компании, аварийки —
      публичный контакт для жильца)
    - LOGGED scope (tenant/landlord) — тот же {'D'} (нет дополнительной
      видимости для коллаборантов)
    - STAFF / LEGAL / HR_RESTRICTED → {'A','B','C','D'} (все группы)

    Пустой `access_levels` (теоретически невозможно: dependency всегда
    возвращает хотя бы PUBLIC) → {'D'} как защитный дефолт.

    Returns: frozenset для immutability (передаётся как параметр в SQL stmt).
    """
    if not access_levels:
        return frozenset({"D"})
    if AccessLevel.STAFF in access_levels or AccessLevel.LEGAL in access_levels:
        return frozenset({"A", "B", "C", "D"})
    if AccessLevel.HR_RESTRICTED in access_levels:
        # HR в принципе не интересуется коллаборантами, но если scope даёт
        # — тот же full visibility.
        return frozenset({"A", "B", "C", "D"})
    # Только PUBLIC / LOGGED / AGENT — публичный контур, видит D.
    return frozenset({"D"})


__all__ = [
    "COLLABORATOR_TYPES",
    "FINANCIAL_GROUPS",
    "LEGAL_ENTITY_TYPES",
    "ONBOARDING_SOURCES",
    "PORTAL_ACCESS_LEVELS",
    "STATUSES",
    "TYPE_TO_FINANCIAL_GROUP",
    "compute_visible_groups",
    "derive_financial_group",
]

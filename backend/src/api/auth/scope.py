"""Scope tags and AccessLevel sets.

Source of truth для двухконтурной модели — ADR-0003.

Scope — это тэг для аудита/отображения («какая логическая роль у пользователя»).
AccessLevel — это единица авторизации, против которой фильтруются ресурсы.

Множества AccessLevel для разных Scope **не вложены** (например, `staff_admin`
не имеет `HR_RESTRICTED`, хотя имеет всё остальное; `staff_hr` имеет
`HR_RESTRICTED`, но не имеет `LEGAL`). Поэтому Scope нельзя сравнивать
линейным порядком — нужно проверять set-membership.

См. ADR-0003 «scope пользователя» — таблица соответствий.
"""

from collections.abc import Iterable
from enum import StrEnum


class AccessLevel(StrEnum):
    """Единица фильтрации ресурсов на уровне хранилища (ADR-0003)."""

    PUBLIC = "PUBLIC"
    LOGGED = "LOGGED"
    AGENT = "AGENT"
    STAFF = "STAFF"
    LEGAL = "LEGAL"
    HR_RESTRICTED = "HR_RESTRICTED"


class Scope(StrEnum):
    """Логический тэг пользователя (используется в audit_log и `/whoami`).

    Не используется напрямую для авторизации — для этого compute_access_levels
    + require_access_level (см. dependency.py).
    """

    GUEST = "guest"
    TENANT = "tenant"
    LANDLORD = "landlord"
    AGENT = "agent"
    STAFF_SUPPORT = "staff_support"
    STAFF_LEGAL = "staff_legal"
    STAFF_HR = "staff_hr"
    STAFF_ADMIN = "staff_admin"


# Source of truth для авторизации — ADR-0003 «scope пользователя».
# Если что-то изменить здесь — нужно обновить ADR (через новый ADR) и тесты.
#
# КРИТИЧЕСКИЙ ИНВАРИАНТ: STAFF_ADMIN НЕ имеет HR_RESTRICTED.
# HR-данные доступны только staff_hr — это явное требование ADR-0003 и ФЗ-152
# (раздел 7 ПЗ «База знаний v1.4» — кадровые документы).
SCOPE_TO_ACCESS_LEVELS: dict[Scope, frozenset[AccessLevel]] = {
    Scope.GUEST: frozenset({AccessLevel.PUBLIC}),
    Scope.TENANT: frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}),
    Scope.LANDLORD: frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}),
    Scope.AGENT: frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.AGENT}),
    Scope.STAFF_SUPPORT: frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.STAFF}),
    Scope.STAFF_LEGAL: frozenset(
        {
            AccessLevel.PUBLIC,
            AccessLevel.LOGGED,
            AccessLevel.STAFF,
            AccessLevel.LEGAL,
        }
    ),
    Scope.STAFF_HR: frozenset(
        {
            AccessLevel.PUBLIC,
            AccessLevel.LOGGED,
            AccessLevel.STAFF,
            AccessLevel.HR_RESTRICTED,
        }
    ),
    Scope.STAFF_ADMIN: frozenset(
        {
            AccessLevel.PUBLIC,
            AccessLevel.LOGGED,
            AccessLevel.AGENT,
            AccessLevel.STAFF,
            AccessLevel.LEGAL,
            # HR_RESTRICTED намеренно отсутствует — ADR-0003.
        }
    ),
}


# Приоритет для compute_scope: первый матчинг в этом списке выигрывает.
# Не используется для авторизации, только для display-тэга.
SCOPE_PRIORITY_FOR_DISPLAY: tuple[Scope, ...] = (
    Scope.STAFF_ADMIN,
    Scope.STAFF_HR,
    Scope.STAFF_LEGAL,
    Scope.STAFF_SUPPORT,
    Scope.AGENT,
    Scope.LANDLORD,
    Scope.TENANT,
)


def compute_scope(roles: Iterable[str]) -> Scope:
    """Возвращает «главный» Scope-тэг для пользователя — для аудита и отображения.

    Если у пользователя несколько ролей — возвращает первую по
    SCOPE_PRIORITY_FOR_DISPLAY. Эта функция **не используется** для
    решения о доступе — для этого compute_access_levels.
    """
    role_set = set(roles)
    for scope in SCOPE_PRIORITY_FOR_DISPLAY:
        if scope.value in role_set:
            return scope
    return Scope.GUEST


def compute_access_levels(roles: Iterable[str]) -> frozenset[AccessLevel]:
    """Возвращает объединение AccessLevel-ов от всех ролей пользователя.

    Это и есть set, против которого фильтруются ресурсы на уровне хранилища
    (см. ADR-0003 «Фильтрация по access_level применяется на уровне хранилища»).

    Пример: пользователь с ролями ['staff_admin', 'staff_hr'] получает union
    AccessLevel'ов — PUBLIC ∪ LOGGED ∪ AGENT ∪ STAFF ∪ LEGAL ∪ HR_RESTRICTED.
    Это намеренное поведение для multi-role пользователей (см. ADR-0007).
    Неизвестные роли игнорируются.
    """
    result: set[AccessLevel] = set()
    for role in roles:
        try:
            scope = Scope(role)
        except ValueError:
            continue  # неизвестная роль — игнорируем
        result.update(SCOPE_TO_ACCESS_LEVELS[scope])
    if not result:
        return SCOPE_TO_ACCESS_LEVELS[Scope.GUEST]
    return frozenset(result)

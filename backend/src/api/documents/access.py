"""Маппинг AccessLevel → confidentiality для документов (E2.8 #56).

Documents используют отдельную access-модель (3 уровня: PUBLIC/INTERNAL/
RESTRICTED) вместо 6-уровневой articles access_level. Этот модуль
конвертирует scope-set пользователя в множество допустимых
confidentiality значений для SQL-фильтра.

ADR-0003 invariant: репозитории документов используют ТОЛЬКО результат
`compute_allowed_confidentialities`, никогда не принимают список
confidentiality напрямую от клиента.

Backlog: AGENT/LEGAL/HR_RESTRICTED маппинги — отдельный решение в kb-files
эпике (когда определим scope доступа agent'ов к договорам, юристов к
LEGAL-маркированным документам, и т.д.).
"""

from src.api.auth.scope import AccessLevel

# Маппинг scope → разрешённые confidentiality. Иерархия:
# - PUBLIC scope видит только PUBLIC документы
# - LOGGED видит PUBLIC + INTERNAL (внутренние документы для логин-ов)
# - STAFF/AGENT видят все 3 уровня (RESTRICTED — для сотрудников)
# AGENT/LEGAL/HR_RESTRICTED — TODO (см. backlog issue).
CONFIDENTIALITY_BY_SCOPE: dict[AccessLevel, frozenset[str]] = {
    AccessLevel.PUBLIC: frozenset({"PUBLIC"}),
    AccessLevel.LOGGED: frozenset({"PUBLIC", "INTERNAL"}),
    AccessLevel.AGENT: frozenset({"PUBLIC", "INTERNAL"}),
    AccessLevel.STAFF: frozenset({"PUBLIC", "INTERNAL", "RESTRICTED"}),
    AccessLevel.LEGAL: frozenset({"PUBLIC", "INTERNAL", "RESTRICTED"}),
    AccessLevel.HR_RESTRICTED: frozenset({"PUBLIC", "INTERNAL", "RESTRICTED"}),
}


def compute_allowed_confidentialities(
    access_levels: frozenset[AccessLevel],
) -> frozenset[str]:
    """Возвращает все confidentiality, доступные текущему scope-set.

    Пустой `access_levels` (теоретически невозможно: dependency всегда
    возвращает хотя бы PUBLIC для guest) → `{PUBLIC}` как защитный
    дефолт, чтобы не упасть в `IN ()` (false-результат).
    """
    if not access_levels:
        return frozenset({"PUBLIC"})
    result: set[str] = set()
    for level in access_levels:
        result.update(CONFIDENTIALITY_BY_SCOPE.get(level, set()))
    return frozenset(result) or frozenset({"PUBLIC"})

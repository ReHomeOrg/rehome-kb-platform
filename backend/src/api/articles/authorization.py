"""Write-side авторизация для articles (ADR-0003 extension).

ADR-0003 расширяется на write: writer не может создать/обновить статью
с `access_level`, к которому у него самого нет доступа на read.
Например, `staff_admin` (без `HR_RESTRICTED`) не может создать
HR_RESTRICTED статью; `staff_support` не может создать LEGAL.

Этот helper переиспользуется PUT/PATCH/DELETE (E4.x).
"""

from src.api.auth.exceptions import ForbiddenError
from src.api.auth.scope import AccessLevel


def ensure_can_write_access_level(
    target: AccessLevel,
    current_levels: frozenset[AccessLevel],
) -> None:
    """403 если `target` отсутствует в `current_levels`.

    Вызывается в router'е сразу после dependency `require_access_level`
    (минимум STAFF) — мы знаем, что writer уже staff. Эта проверка
    добивает Level-2 ADR-0003 invariant.
    """
    if target not in current_levels:
        raise ForbiddenError(
            detail="Cannot create or modify article with access_level you don't have"
        )

"""Auth-relevant endpoints (smoke и self-introspection).

`GET /api/v1/whoami` — отладочный endpoint, отдаёт scope и роли текущего
пользователя по предъявленному токену. Полезен для:
- Smoke-теста auth-инфраструктуры (E1.3.2)
- Frontend дебага (есть ли валидный кукей)
- Integration-теста с реальным Keycloak (E1.3.4)
"""

from typing import Any

from fastapi import APIRouter, Depends

from src.api.auth.dependency import (
    get_current_access_levels,
    get_current_claims,
    get_current_roles,
    get_current_scope,
)
from src.api.auth.scope import AccessLevel, Scope

router = APIRouter(tags=["Auth"])


@router.get("/whoami", summary="Информация о текущем пользователе по токену")
def whoami(
    claims: dict[str, Any] | None = Depends(get_current_claims),
    scope: Scope = Depends(get_current_scope),
    roles: list[str] = Depends(get_current_roles),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
) -> dict[str, Any]:
    """Возвращает scope, роли и access_levels пользователя.

    Без токена → анонимный guest. С невалидным токеном → 401.
    """
    return {
        "scope": scope.value,
        "sub": claims.get("sub", "") if claims else "",
        "username": claims.get("preferred_username", "") if claims else "",
        "roles": roles,
        "access_levels": sorted(level.value for level in access_levels),
    }

"""FastAPI dependencies для auth.

Использование:
```python
from src.api.auth import AccessLevel
from src.api.auth.dependency import require_access_level, get_current_scope

@router.get("/articles/{slug}")
def get_article(
    slug: str,
    scope: Scope = Depends(get_current_scope),
    _: None = Depends(require_access_level(AccessLevel.LOGGED)),
):
    # ...
```

ВАЖНО (ADR-0003): функция get_current_access_levels — единственный путь
получить access_level в endpoint. scope/access_level **никогда не должны**
приниматься от клиента — это операционный костыль из ТЗ 5.2.
"""

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from fastapi import Depends, Request

from src.api.auth.exceptions import ForbiddenError
from src.api.auth.oidc import OIDCVerifier
from src.api.auth.scope import (
    AccessLevel,
    Scope,
    compute_access_levels,
    compute_scope,
)
from src.api.config import Settings, get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_verifier_cached(
    _jwks_url: str, _issuer: str, _audience: str, _verify_aud: bool
) -> OIDCVerifier:
    """LRU-cache по конфигу — переинициализация только при смене env.

    Параметры формируют cache-key (через `lru_cache`); сам verifier создаётся
    из `get_settings()` (читает env). Префикс `_` указывает, что параметры
    используются опосредованно (через хеширование), не в теле функции.
    """
    return OIDCVerifier(get_settings())


def get_verifier(
    settings: Settings = Depends(get_settings),
) -> OIDCVerifier:
    """Возвращает OIDC verifier (кэшированный по конфигу)."""
    return _get_verifier_cached(
        settings.keycloak_jwks_url,
        settings.keycloak_issuer,
        settings.keycloak_audience,
        settings.verify_aud,
    )


def get_token_from_request(request: Request) -> str | None:
    """Извлекает JWT из запроса.

    Политика приоритетов (защита от token smuggling):
    1. `Authorization: Bearer <token>` (m2m) — приоритетный
    2. `Cookie: kb_session=<token>` (browser) — fallback
    3. Если присутствуют оба — берётся Authorization, в лог пишется
       security-warning (логируется попытка подмешать токены).

    Возвращает None если ни одного источника нет (анонимный гость).
    """
    auth_header = request.headers.get("Authorization")
    cookie_token = request.cookies.get("kb_session")

    if auth_header and cookie_token:
        logger.warning(
            "auth.token_source_conflict",
            extra={
                "client_ip": request.client.host if request.client else None,
                "resolution": "authorization_header_wins",
            },
        )

    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ").strip() or None
    if cookie_token:
        return cookie_token
    return None


def get_current_claims(
    request: Request,
    verifier: OIDCVerifier = Depends(get_verifier),
) -> dict[str, Any] | None:
    """Валидирует и возвращает claims, или None если токена нет.

    Поднимает InvalidTokenError (401) если токен есть, но невалиден.
    """
    token = get_token_from_request(request)
    if token is None:
        return None
    return verifier.verify(token)


def get_current_roles(
    claims: dict[str, Any] | None = Depends(get_current_claims),
) -> list[str]:
    """Извлекает список realm_access.roles из claims (или [] если нет токена)."""
    if claims is None:
        return []
    realm_access = claims.get("realm_access", {})
    roles = realm_access.get("roles", [])
    if not isinstance(roles, list):
        return []
    return [r for r in roles if isinstance(r, str)]


def get_current_scope(
    roles: list[str] = Depends(get_current_roles),
) -> Scope:
    """Главный Scope-тэг пользователя — для аудита и `/whoami`.

    Не использовать для авторизации (см. require_access_level).
    """
    return compute_scope(roles)


def get_current_access_levels(
    roles: list[str] = Depends(get_current_roles),
) -> frozenset[AccessLevel]:
    """Возвращает set AccessLevel-ов для фильтрации ресурсов в хранилище.

    Это **единственный путь** проверки прав в endpoint'ах. Никогда не
    принимайте scope/access_level из клиента. См. ADR-0003.

    Реальная фильтрация — на уровне SQL/Qdrant запросов (`WHERE access_level
    IN (...)`); этот set передаётся в query layer. См. ПЗ API 2.3.
    """
    return compute_access_levels(roles)


def require_access_level(required: AccessLevel) -> Callable[..., None]:
    """FastAPI Depends-factory — 403 если у пользователя нет required level.

    ВАЖНО: эта проверка — комплимент к storage-level фильтру (ADR-0003),
    не замена. Endpoint'ы всё равно фильтруют SELECT по access_level в БД.
    """

    def _dep(
        access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    ) -> None:
        if required not in access_levels:
            raise ForbiddenError(detail=f"Required access_level: {required.value}")

    return _dep

"""OIDC token verification through Keycloak JWKS.

См. ADR-0007 (Keycloak realm structure) и ПЗ «API базы знаний v1.3» раздел 2.2
(два режима auth: m2m + browser cookie).

Ключевые security-инварианты:
- Алгоритм подписи **жёстко фиксирован как RS256** (защита от `alg: none` атаки).
- JWKS-кеш через PyJWKClient с автоматическим refresh при unknown `kid`.
- Логи **никогда** не содержат полного JWT (защита ПДн).
"""

import logging
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError as PyJWTInvalidTokenError

from src.api.auth.exceptions import InvalidTokenError
from src.api.config import Settings

logger = logging.getLogger(__name__)


class OIDCVerifier:
    """Кэшируемый verifier для JWT от Keycloak.

    PyJWKClient внутри держит TTL-кеш публичных ключей и автоматически
    делает refresh при появлении JWT с неизвестным `kid` (по умолчанию
    lifespan=300s; см. PyJWT docs).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks_client = PyJWKClient(settings.keycloak_jwks_url)
        if not settings.verify_aud:
            # Audience verification отключена через KC_VERIFY_AUD=false override.
            # По умолчанию verify_aud=True (закрыто в Issue #21 / E1.3.4 после
            # добавления audience mapper в realm-export.json).
            logger.warning(
                "auth.audience_verification_disabled",
                extra={"reason": "KC_VERIFY_AUD=false override"},
            )

    def verify(self, token: str) -> dict[str, Any]:
        """Валидирует JWT и возвращает claims.

        Поднимает InvalidTokenError при:
        - неверной подписи
        - истечении срока
        - неверном issuer
        - неверном audience (если verify_aud=True)
        - использовании запрещённого алгоритма (например, `none`)
        - отсутствии `kid` или невозможности fetch'нуть key

        Полный JWT никогда не попадает в логи. Логируется только sub
        (UUID), kid и тип ошибки.
        """
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token).key
        except Exception as e:
            # PyJWKClient может бросить разные исключения (jose, request, etc.)
            logger.warning(
                "auth.jwks_key_fetch_failed",
                extra={"error_type": type(e).__name__},
            )
            raise InvalidTokenError("Cannot resolve signing key") from e

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=signing_key,
                algorithms=["RS256"],  # жёстко: защита от `alg: none`
                audience=self._settings.keycloak_audience,
                issuer=self._settings.keycloak_issuer,
                leeway=30,  # 30s допуск на clock skew
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": self._settings.verify_aud,
                    "require": ["exp", "iss"],
                },
            )
        except PyJWTInvalidTokenError as e:
            logger.warning(
                "auth.token_invalid",
                extra={"error_type": type(e).__name__},
            )
            raise InvalidTokenError(f"Token validation failed: {type(e).__name__}") from e

        # Структурный лог без полного токена: только sub и kid.
        unverified_header = jwt.get_unverified_header(token)
        logger.debug(
            "auth.token_verified",
            extra={
                "sub": claims.get("sub", ""),
                "kid": unverified_header.get("kid", ""),
            },
        )
        return claims

"""Step-up MFA validation для X-MFA-Token header (ADR-0019 §«MFA», RFC 9470).

Pattern:
- Main bearer token = standard m2m / browser session (single-factor OK).
- X-MFA-Token header = separate JWT (issued by Keycloak after MFA challenge,
  e.g. TOTP/FIDO2). Must:
  - Sign correctly via same Keycloak JWKS (RS256).
  - Have `acr` claim equal to `settings.kc_mfa_required_acr` (default `"2"`).
  - Have `sub` matching main user's sub (anti-token-swap).
  - Not be expired (verifier handles via verify_exp).

Used on sensitive admin endpoints (PATCH /admin/system-config, PUT /admin/
llm/active) which were honest-stub'нуты в #264 — `mfa_token_provided` flag
audited but not validated. Этот module landит real validation.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, Header, HTTPException

from src.api.auth.dependency import get_verifier, require_authenticated
from src.api.auth.exceptions import InvalidTokenError
from src.api.auth.oidc import OIDCVerifier
from src.api.config import Settings, get_settings

logger = logging.getLogger(__name__)


class MFATokenError(HTTPException):
    """403: step-up MFA token missing, invalid, or insufficient acr."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=403, detail=detail)


def validate_mfa_token(
    *,
    token: str,
    main_user_sub: str,
    verifier: OIDCVerifier,
    settings: Settings,
) -> dict[str, Any]:
    """Verify X-MFA-Token JWT и return its claims.

    Raises MFATokenError (403) на:
    - Invalid signature / expired / wrong audience / issuer.
    - `sub` mismatch с main_user_sub (token-swap attempt).
    - `acr` claim missing или != configured threshold.

    Returns validated claims on success.
    """
    try:
        claims = verifier.verify(token)
    except InvalidTokenError as exc:
        logger.warning(
            "mfa.token_invalid",
            extra={"sub": main_user_sub, "error_type": type(exc).__name__},
        )
        raise MFATokenError(f"X-MFA-Token validation failed: {exc}") from exc

    token_sub = claims.get("sub")
    if token_sub != main_user_sub:
        logger.warning(
            "mfa.sub_mismatch",
            extra={"main_sub": main_user_sub, "token_sub": token_sub},
        )
        raise MFATokenError("X-MFA-Token sub mismatch")

    acr = claims.get("acr")
    if acr is None or str(acr) != settings.kc_mfa_required_acr:
        logger.warning(
            "mfa.insufficient_acr",
            extra={
                "sub": main_user_sub,
                "got_acr": str(acr) if acr is not None else None,
                "required_acr": settings.kc_mfa_required_acr,
            },
        )
        raise MFATokenError(
            f"X-MFA-Token requires acr={settings.kc_mfa_required_acr} "
            f"(step-up MFA); got acr={acr!r}"
        )

    return claims


def require_step_up_mfa(
    claims: dict[str, Any] = Depends(require_authenticated),
    verifier: OIDCVerifier = Depends(get_verifier),
    settings: Settings = Depends(get_settings),
    x_mfa_token: str | None = Header(default=None, alias="X-MFA-Token"),
) -> dict[str, Any]:
    """FastAPI dependency — 403 если X-MFA-Token missing или invalid.

    Returns validated MFA claims (caller can audit `acr` / `iat` / `auth_time`).
    Main user sub taken from `require_authenticated` chain.
    """
    if not x_mfa_token:
        logger.info(
            "mfa.token_missing",
            extra={"sub": claims.get("sub")},
        )
        raise MFATokenError("X-MFA-Token header required for this operation")

    return validate_mfa_token(
        token=x_mfa_token,
        main_user_sub=str(claims.get("sub", "")),
        verifier=verifier,
        settings=settings,
    )


__all__ = ["MFATokenError", "require_step_up_mfa", "validate_mfa_token"]

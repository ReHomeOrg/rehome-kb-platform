"""Unit tests для X-MFA-Token validation (ADR-0019 §«MFA»)."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.api.auth.exceptions import InvalidTokenError
from src.api.auth.mfa import MFATokenError, validate_mfa_token
from src.api.config import Settings


def _settings_with_acr(required_acr: str = "2") -> Settings:
    """Build minimal Settings with required acr set."""
    s = MagicMock(spec=Settings)
    s.kc_mfa_required_acr = required_acr
    return s


def test_validate_mfa_token_happy_path(make_jwt: Callable[..., str]) -> None:
    """Valid signature + acr=2 + matching sub → returns claims."""
    sub = str(uuid4())
    token = make_jwt(sub=sub, extra_claims={"acr": "2"})

    # Real verifier через _get_verifier_cached + _patched_jwks fixture.
    from src.api.auth.dependency import _get_verifier_cached
    from src.api.config import get_settings

    s = get_settings()
    verifier = _get_verifier_cached(
        s.keycloak_jwks_url, s.keycloak_issuer, s.keycloak_audience, s.verify_aud
    )
    claims = validate_mfa_token(
        token=token,
        main_user_sub=sub,
        verifier=verifier,
        settings=_settings_with_acr("2"),
    )
    assert claims["sub"] == sub
    assert claims["acr"] == "2"


def test_validate_mfa_token_invalid_signature_raises(make_jwt: Callable[..., str]) -> None:
    """Malformed token → MFATokenError."""
    from src.api.auth.dependency import _get_verifier_cached
    from src.api.config import get_settings

    s = get_settings()
    verifier = _get_verifier_cached(
        s.keycloak_jwks_url, s.keycloak_issuer, s.keycloak_audience, s.verify_aud
    )
    with pytest.raises(MFATokenError):
        validate_mfa_token(
            token="not-a-jwt",
            main_user_sub=str(uuid4()),
            verifier=verifier,
            settings=_settings_with_acr("2"),
        )


def test_validate_mfa_token_sub_mismatch_raises(make_jwt: Callable[..., str]) -> None:
    """MFA token for другой пользователь → MFATokenError."""
    other_sub = str(uuid4())
    main_sub = str(uuid4())
    token = make_jwt(sub=other_sub, extra_claims={"acr": "2"})

    from src.api.auth.dependency import _get_verifier_cached
    from src.api.config import get_settings

    s = get_settings()
    verifier = _get_verifier_cached(
        s.keycloak_jwks_url, s.keycloak_issuer, s.keycloak_audience, s.verify_aud
    )
    with pytest.raises(MFATokenError, match="sub mismatch"):
        validate_mfa_token(
            token=token,
            main_user_sub=main_sub,
            verifier=verifier,
            settings=_settings_with_acr("2"),
        )


def test_validate_mfa_token_insufficient_acr_raises(make_jwt: Callable[..., str]) -> None:
    """acr=1 → MFATokenError."""
    sub = str(uuid4())
    token = make_jwt(sub=sub, extra_claims={"acr": "1"})

    from src.api.auth.dependency import _get_verifier_cached
    from src.api.config import get_settings

    s = get_settings()
    verifier = _get_verifier_cached(
        s.keycloak_jwks_url, s.keycloak_issuer, s.keycloak_audience, s.verify_aud
    )
    with pytest.raises(MFATokenError, match="acr"):
        validate_mfa_token(
            token=token,
            main_user_sub=sub,
            verifier=verifier,
            settings=_settings_with_acr("2"),
        )


def test_validate_mfa_token_missing_acr_raises(make_jwt: Callable[..., str]) -> None:
    """No acr claim → MFATokenError."""
    sub = str(uuid4())
    token = make_jwt(sub=sub)  # no extra_claims

    from src.api.auth.dependency import _get_verifier_cached
    from src.api.config import get_settings

    s = get_settings()
    verifier = _get_verifier_cached(
        s.keycloak_jwks_url, s.keycloak_issuer, s.keycloak_audience, s.verify_aud
    )
    with pytest.raises(MFATokenError):
        validate_mfa_token(
            token=token,
            main_user_sub=sub,
            verifier=verifier,
            settings=_settings_with_acr("2"),
        )


def test_validate_mfa_token_alternate_acr_value(make_jwt: Callable[..., str]) -> None:
    """Configurable acr — e.g. Keycloak emitting `aal2` instead of `2`."""
    sub = str(uuid4())
    token = make_jwt(sub=sub, extra_claims={"acr": "aal2"})

    from src.api.auth.dependency import _get_verifier_cached
    from src.api.config import get_settings

    s = get_settings()
    verifier = _get_verifier_cached(
        s.keycloak_jwks_url, s.keycloak_issuer, s.keycloak_audience, s.verify_aud
    )
    # With kc_mfa_required_acr="aal2" → accepts.
    claims = validate_mfa_token(
        token=token,
        main_user_sub=sub,
        verifier=verifier,
        settings=_settings_with_acr("aal2"),
    )
    assert claims["acr"] == "aal2"
    # With kc_mfa_required_acr="2" (default) → rejects.
    with pytest.raises(MFATokenError):
        validate_mfa_token(
            token=token,
            main_user_sub=sub,
            verifier=verifier,
            settings=_settings_with_acr("2"),
        )


def test_validate_mfa_token_expired_raises(make_jwt: Callable[..., str]) -> None:
    """Expired token → MFATokenError (через InvalidTokenError из verifier)."""
    sub = str(uuid4())
    token = make_jwt(sub=sub, extra_claims={"acr": "2"}, expired=True)

    from src.api.auth.dependency import _get_verifier_cached
    from src.api.config import get_settings

    s = get_settings()
    verifier = _get_verifier_cached(
        s.keycloak_jwks_url, s.keycloak_issuer, s.keycloak_audience, s.verify_aud
    )
    with pytest.raises(MFATokenError):
        validate_mfa_token(
            token=token,
            main_user_sub=sub,
            verifier=verifier,
            settings=_settings_with_acr("2"),
        )


def test_mfa_error_status_403() -> None:
    """MFATokenError всегда возвращает HTTP 403."""
    exc = MFATokenError("test")
    assert exc.status_code == 403
    assert exc.detail == "test"


def test_validate_propagates_invalid_token_error() -> None:
    """Если verifier raises неformat InvalidTokenError, оборачиваем в MFATokenError."""
    verifier = MagicMock()
    verifier.verify.side_effect = InvalidTokenError("malformed")
    with pytest.raises(MFATokenError, match="validation failed"):
        validate_mfa_token(
            token="x",
            main_user_sub="s",
            verifier=verifier,
            settings=_settings_with_acr("2"),
        )

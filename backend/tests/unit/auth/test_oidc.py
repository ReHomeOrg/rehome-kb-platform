"""Тесты OIDCVerifier: signature, expiry, audience, algorithm."""

import logging
from collections.abc import Callable

import jwt
import pytest

from src.api.auth.exceptions import InvalidTokenError
from src.api.auth.oidc import OIDCVerifier
from src.api.config import Settings


def test_verify_valid_token(verifier: OIDCVerifier, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["staff_support"])
    claims = verifier.verify(token)
    assert claims["sub"] == "test-user-uuid"
    assert claims["realm_access"]["roles"] == ["staff_support"]


def test_verify_expired_token_rejected(
    verifier: OIDCVerifier, make_jwt: Callable[..., str]
) -> None:
    token = make_jwt(roles=["tenant"], expired=True)
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_verify_wrong_audience_rejected(
    verifier: OIDCVerifier, make_jwt: Callable[..., str]
) -> None:
    token = make_jwt(roles=["tenant"], audience="some-other-audience")
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_verify_wrong_issuer_rejected(verifier: OIDCVerifier, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], issuer="http://evil.example.com/realms/rehome")
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_verify_alg_none_rejected(
    verifier: OIDCVerifier,
) -> None:
    """JWT с `alg: none` (unsigned) ДОЛЖЕН быть отвергнут.

    Известная атака CVE-2015-2951 — некоторые JWT-библиотеки принимают
    unsigned tokens. PyJWT защищён, потому что мы передаём
    `algorithms=['RS256']` явно.
    """
    # Создаём unsigned JWT (alg=none). PyJWT требует explicit None key + algorithm.
    payload = {
        "iss": "http://localhost:8080/realms/rehome",
        "aud": "rehome-platform-m2m",
        "sub": "attacker",
        "iat": 1700000000,
        "exp": 9999999999,
        "realm_access": {"roles": ["staff_admin"]},
    }
    token = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(InvalidTokenError):
        verifier.verify(token)


def test_verify_malformed_token_rejected(verifier: OIDCVerifier) -> None:
    with pytest.raises(InvalidTokenError):
        verifier.verify("not.a.valid.jwt")


def test_verify_signature_tampered_rejected(
    verifier: OIDCVerifier, make_jwt: Callable[..., str]
) -> None:
    """Если payload изменён после подписи — signature mismatch → отвергаем."""
    token = make_jwt(roles=["tenant"])
    parts = token.split(".")
    # Меняем payload (последний байт) — signature становится невалидной.
    tampered = parts[0] + "." + parts[1][:-2] + "XX" + "." + parts[2]
    with pytest.raises(InvalidTokenError):
        verifier.verify(tampered)


def test_logger_does_not_emit_full_jwt(
    verifier: OIDCVerifier,
    make_jwt: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ФЗ-152: логи не должны содержать полного JWT (защита ПДн).

    JWT содержит sub (UUID), preferred_username, email — это ПДн.
    Логирование полного токена в plain text — нарушение.
    """
    caplog.set_level(logging.DEBUG, logger="src.api.auth.oidc")
    token = make_jwt(roles=["staff_support"], username="alice@example.com")
    verifier.verify(token)
    # Полный token не должен встречаться в логах.
    for record in caplog.records:
        assert token not in record.getMessage()
        # Username (email) тоже не должен утечь в plain text сообщения.
        assert "alice@example.com" not in record.getMessage()


def test_audience_verification_disabled_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """При verify_aud=False логируется security-warning при init verifier."""
    monkeypatch.setenv("KC_VERIFY_AUD", "false")
    from src.api.config import get_settings

    caplog.set_level(logging.WARNING, logger="src.api.auth.oidc")
    OIDCVerifier(get_settings())
    assert any("auth.audience_verification_disabled" in r.getMessage() for r in caplog.records)


def test_settings_has_keycloak_urls(test_settings: Settings) -> None:
    assert test_settings.keycloak_issuer == "http://localhost:8080/realms/rehome"
    assert (
        test_settings.keycloak_jwks_url
        == "http://localhost:8080/realms/rehome/protocol/openid-connect/certs"
    )

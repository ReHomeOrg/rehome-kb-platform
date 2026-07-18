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


# --- CC-1: делегированные audiences (вариант A, аддитивный accept-list) ----------


def _verifier_with_delegated(monkeypatch: pytest.MonkeyPatch, delegated: str) -> OIDCVerifier:
    """Verifier с KC_DELEGATED_AUDIENCES (остальной keycloak-конфиг = как в test_settings)."""
    from src.api.config import get_settings

    monkeypatch.setenv("KC_URL", "http://localhost:8080")
    monkeypatch.setenv("KC_REALM", "rehome")
    monkeypatch.setenv("KC_AUDIENCE", "rehome-platform-m2m")
    monkeypatch.setenv("KC_VERIFY_AUD", "true")
    monkeypatch.setenv("KC_DELEGATED_AUDIENCES", delegated)
    return OIDCVerifier(get_settings())


def test_delegated_audience_accepted_when_configured(
    monkeypatch: pytest.MonkeyPatch, make_jwt: Callable[..., str]
) -> None:
    # Делегированный токен Консьержа (audience=kb-search) принимается, когда aud в accept-list.
    verifier = _verifier_with_delegated(monkeypatch, "kb-search,rehome-platform")
    claims = verifier.verify(make_jwt(roles=["tenant"], audience="kb-search"))
    assert claims["aud"] == "kb-search"


def test_second_delegated_audience_accepted(
    monkeypatch: pytest.MonkeyPatch, make_jwt: Callable[..., str]
) -> None:
    verifier = _verifier_with_delegated(monkeypatch, "kb-search,rehome-platform")
    assert verifier.verify(make_jwt(audience="rehome-platform"))["aud"] == "rehome-platform"


def test_primary_audience_still_accepted_with_delegated(
    monkeypatch: pytest.MonkeyPatch, make_jwt: Callable[..., str]
) -> None:
    # SECURITY/backcompat: существующие m2m-токены (rehome-platform-m2m) НЕ ломаются.
    verifier = _verifier_with_delegated(monkeypatch, "kb-search")
    assert verifier.verify(make_jwt(audience="rehome-platform-m2m"))["aud"] == "rehome-platform-m2m"


def test_delegated_audience_rejected_when_empty(
    monkeypatch: pytest.MonkeyPatch, make_jwt: Callable[..., str]
) -> None:
    # Default (KC_DELEGATED_AUDIENCES пусто) → поведение не меняется: kb-search-aud отвергается.
    verifier = _verifier_with_delegated(monkeypatch, "")
    with pytest.raises(InvalidTokenError):
        verifier.verify(make_jwt(audience="kb-search"))


def test_unlisted_audience_still_rejected_with_delegated(
    monkeypatch: pytest.MonkeyPatch, make_jwt: Callable[..., str]
) -> None:
    # SECURITY: aud вне accept-list по-прежнему 401 (не «принимаем что угодно»).
    verifier = _verifier_with_delegated(monkeypatch, "kb-search")
    with pytest.raises(InvalidTokenError):
        verifier.verify(make_jwt(audience="evil-service"))


def test_token_with_aud_array_accepted_by_intersection(
    monkeypatch: pytest.MonkeyPatch, make_jwt: Callable[..., str]
) -> None:
    # Целевой CC-1-кейс: делегированный токен несёт aud СПИСКОМ (напр. [account, kb-search]).
    # Принимается, если хотя бы один элемент — в accept-list (intersection).
    verifier = _verifier_with_delegated(monkeypatch, "kb-search")
    token = make_jwt(roles=["tenant"], extra_claims={"aud": ["account", "kb-search"]})
    assert verifier.verify(token)["aud"] == ["account", "kb-search"]


def test_token_with_aud_array_none_listed_rejected(
    monkeypatch: pytest.MonkeyPatch, make_jwt: Callable[..., str]
) -> None:
    # aud-массив без пересечения с accept-list → 401 (SECURITY).
    verifier = _verifier_with_delegated(monkeypatch, "kb-search")
    with pytest.raises(InvalidTokenError):
        verifier.verify(make_jwt(extra_claims={"aud": ["account", "other-service"]}))


def test_accepted_audiences_default_is_primary_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.config import get_settings

    monkeypatch.setenv("KC_AUDIENCE", "rehome-platform-m2m")
    monkeypatch.delenv("KC_DELEGATED_AUDIENCES", raising=False)
    assert get_settings().accepted_audiences == ["rehome-platform-m2m"]


def test_accepted_audiences_includes_delegated_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.config import get_settings

    monkeypatch.setenv("KC_AUDIENCE", "rehome-platform-m2m")
    # дубль основного + пробелы + пустой хвост — дедуп/стрип.
    monkeypatch.setenv(
        "KC_DELEGATED_AUDIENCES", " kb-search , rehome-platform , rehome-platform-m2m ,"
    )
    assert get_settings().accepted_audiences == [
        "rehome-platform-m2m",
        "kb-search",
        "rehome-platform",
    ]

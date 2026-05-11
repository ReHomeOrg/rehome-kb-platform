"""Shared fixtures для auth-тестов.

Не используем сетевых запросов. JWKS-client мокается monkeypatch'ом —
возвращает наш test-private-key. JWT создаются с помощью cryptography +
PyJWT.encode.
"""

from collections.abc import Callable, Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from src.api.auth.dependency import _get_verifier_cached
from src.api.auth.oidc import OIDCVerifier
from src.api.config import Settings, get_settings
from src.api.main import app

TEST_KID = "test-kid-2026-05-12"
TEST_ISSUER = "http://localhost:8080/realms/rehome"
TEST_AUDIENCE = "rehome-platform-m2m"


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    """Один RSA keypair на всю сессию (генерация дорогая)."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key()
    return private, public


@pytest.fixture(scope="session")
def private_pem(rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]) -> bytes:
    private, _ = rsa_keypair
    return private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture(scope="session")
def public_pem(rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]) -> bytes:
    _, public = rsa_keypair
    return public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


@pytest.fixture
def make_jwt(private_pem: bytes) -> Callable[..., str]:
    """Factory для тестовых JWT с правильной подписью (RS256, test_kid)."""

    def _make(
        roles: list[str] | None = None,
        sub: str = "test-user-uuid",
        username: str = "testuser",
        audience: str = TEST_AUDIENCE,
        issuer: str = TEST_ISSUER,
        expired: bool = False,
        algorithm: str = "RS256",
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        import time

        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": issuer,
            "aud": audience,
            "sub": sub,
            "preferred_username": username,
            "iat": now - 10,
            "exp": now - 60 if expired else now + 3600,
            "realm_access": {"roles": roles or []},
        }
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(
            payload,
            key=private_pem,
            algorithm=algorithm,
            headers={"kid": TEST_KID},
        )

    return _make


@pytest.fixture(autouse=True)
def _reset_verifier_cache() -> Iterator[None]:
    """Не даём LRU-кешу verifier'а утекать между тестами."""
    _get_verifier_cached.cache_clear()
    yield
    _get_verifier_cached.cache_clear()


@pytest.fixture(autouse=True)
def _patched_jwks(
    monkeypatch: pytest.MonkeyPatch,
    public_pem: bytes,
    rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey],
) -> None:
    """Подменяет PyJWKClient.get_signing_key_from_jwt чтобы возвращал наш ключ.

    Никаких сетевых запросов к http://localhost:8080 во время тестов.
    """
    _, public = rsa_keypair

    class _FakeKey:
        def __init__(self, public_key: Any) -> None:
            self.key = public_key

    def _fake_get(self: Any, token: str) -> _FakeKey:
        return _FakeKey(public)

    monkeypatch.setattr("jwt.PyJWKClient.get_signing_key_from_jwt", _fake_get)


@pytest.fixture
def test_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings с фиксированными значениями для воспроизводимости тестов."""
    monkeypatch.setenv("KC_URL", "http://localhost:8080")
    monkeypatch.setenv("KC_REALM", "rehome")
    monkeypatch.setenv("KC_AUDIENCE", TEST_AUDIENCE)
    monkeypatch.setenv("KC_VERIFY_AUD", "true")  # в большинстве тестов проверяем aud
    return get_settings()


@pytest.fixture
def verifier(test_settings: Settings) -> OIDCVerifier:
    return OIDCVerifier(test_settings)


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    """TestClient с тестовыми KC settings и без интернета (JWKS пропатчен)."""
    with TestClient(app) as test_client:
        yield test_client

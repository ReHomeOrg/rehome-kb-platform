"""Unit-тесты HMAC signing (E5.2 #89)."""

from src.api.webhooks.signing import (
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    compute_signature,
    verify_signature,
)


def test_signature_starts_with_sha256_prefix() -> None:
    sig = compute_signature("secret", b"body")
    assert sig.startswith(SIGNATURE_PREFIX)


def test_signature_is_deterministic() -> None:
    s1 = compute_signature("secret", b"body")
    s2 = compute_signature("secret", b"body")
    assert s1 == s2


def test_signature_changes_with_secret() -> None:
    a = compute_signature("secret-a", b"body")
    b = compute_signature("secret-b", b"body")
    assert a != b


def test_signature_changes_with_body() -> None:
    a = compute_signature("secret", b"body-a")
    b = compute_signature("secret", b"body-b")
    assert a != b


def test_verify_valid_signature() -> None:
    body = b'{"event":"article.published"}'
    sig = compute_signature("secret-xyz", body)
    assert verify_signature("secret-xyz", body, sig) is True


def test_verify_wrong_signature() -> None:
    body = b"body"
    assert verify_signature("secret", body, "sha256=00") is False


def test_verify_wrong_secret() -> None:
    body = b"body"
    sig = compute_signature("secret-a", body)
    assert verify_signature("secret-b", body, sig) is False


def test_header_name_constant() -> None:
    assert SIGNATURE_HEADER == "X-Rehome-Signature"

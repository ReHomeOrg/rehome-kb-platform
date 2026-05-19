"""Unit tests для hr/crypto (#234, ADR-0018)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.api.config import Settings
from src.api.hr.crypto import (
    HrEncryptionKeyError,
    decrypt_pii,
    encrypt_pii,
)


def _settings(**over: object) -> Settings:
    return Settings.model_validate(over)


# ---------------------------------------------------------------------------
# encrypt / decrypt roundtrip


def test_roundtrip_basic() -> None:
    s = _settings()
    ciphertext = encrypt_pii("1234 567890", s)
    assert ciphertext is not None
    assert ciphertext != b"1234 567890"  # actually encrypted
    plaintext = decrypt_pii(ciphertext, s)
    assert plaintext == "1234 567890"


def test_roundtrip_cyrillic() -> None:
    s = _settings()
    ct = encrypt_pii("Иванов И.И.", s)
    assert decrypt_pii(ct, s) == "Иванов И.И."


def test_roundtrip_inn_12_digits() -> None:
    s = _settings()
    ct = encrypt_pii("770700700007", s)
    assert decrypt_pii(ct, s) == "770700700007"


# ---------------------------------------------------------------------------
# None / empty passthrough


def test_encrypt_none_returns_none() -> None:
    assert encrypt_pii(None, _settings()) is None


def test_encrypt_empty_string_returns_none() -> None:
    """Empty string normalize'ится в None — `«не заполнено»` semantic."""
    assert encrypt_pii("", _settings()) is None


def test_decrypt_none_returns_none() -> None:
    assert decrypt_pii(None, _settings()) is None


# ---------------------------------------------------------------------------
# Different ciphertext each call (Fernet uses random IV per encrypt)


def test_ciphertext_differs_per_encrypt() -> None:
    """Fernet — randomized IV → одно и то же plaintext шифруется
    разной ciphertext'ой каждый раз (защита от replay analysis)."""
    s = _settings()
    a = encrypt_pii("770700700007", s)
    b = encrypt_pii("770700700007", s)
    assert a != b
    # Но decrypt оба возвращают тот же plaintext.
    assert decrypt_pii(a, s) == decrypt_pii(b, s) == "770700700007"


# ---------------------------------------------------------------------------
# Key rotation (legacy key)


def test_legacy_key_decrypts_old_ciphertext() -> None:
    """Сценарий rotation: создан старым ключом, читается с новым primary
    + legacy fallback."""
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")

    # Step 1: encrypt с old key (primary).
    s_old = _settings(HR_ENCRYPTION_KEY=old_key)
    ct = encrypt_pii("770700700007", s_old)

    # Step 2: rotate — new key primary, old как legacy.
    s_new = _settings(
        HR_ENCRYPTION_KEY=new_key,
        HR_ENCRYPTION_KEY_LEGACY=old_key,
    )
    # Decrypt success via MultiFernet перебор.
    assert decrypt_pii(ct, s_new) == "770700700007"


def test_new_encrypt_uses_primary_not_legacy() -> None:
    """После rotation: new encrypts с primary, не с legacy."""
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    s_rotation = _settings(
        HR_ENCRYPTION_KEY=new_key,
        HR_ENCRYPTION_KEY_LEGACY=old_key,
    )
    ct = encrypt_pii("770700700007", s_rotation)
    # Decrypt with primary-only Settings (без legacy) — должно работать,
    # т.к. encrypt'или primary key.
    s_primary_only = _settings(HR_ENCRYPTION_KEY=new_key)
    assert decrypt_pii(ct, s_primary_only) == "770700700007"


def test_corrupted_ciphertext_returns_none() -> None:
    """InvalidToken → gracefully degrade, не raise."""
    s = _settings()
    assert decrypt_pii(b"not-real-ciphertext", s) is None


# ---------------------------------------------------------------------------
# Key validation


def test_invalid_key_format_raises() -> None:
    s = _settings(HR_ENCRYPTION_KEY="too-short")
    with pytest.raises(HrEncryptionKeyError, match="32-byte"):
        encrypt_pii("x", s)


def test_dev_key_in_production_raises() -> None:
    """ADR-0018: dev sentinel key strictly запрещён в production."""
    s = _settings(REHOME_ENV="production")  # default key = dev sentinel
    with pytest.raises(HrEncryptionKeyError, match="dev sentinel"):
        encrypt_pii("x", s)


def test_dev_key_in_dev_environment_works() -> None:
    """Dev / test environment — sentinel key OK."""
    s = _settings(REHOME_ENV="dev")
    ct = encrypt_pii("test", s)
    assert decrypt_pii(ct, s) == "test"


def test_test_environment_dev_key_works() -> None:
    s = _settings(REHOME_ENV="test")
    ct = encrypt_pii("x", s)
    assert decrypt_pii(ct, s) == "x"


def test_invalid_legacy_key_raises() -> None:
    s = _settings(HR_ENCRYPTION_KEY_LEGACY="invalid")
    with pytest.raises(HrEncryptionKeyError, match="LEGACY"):
        encrypt_pii("x", s)

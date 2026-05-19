"""HR ПДн encryption helpers (#234, ADR-0018 Variant A).

Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256 — `cryptography`
package). Primary key из `Settings.hr_encryption_key`; optional legacy
key для rotation period (decrypt-only fallback).

Public API:
- `encrypt_pii(plaintext) -> bytes | None` — None passthrough.
- `decrypt_pii(ciphertext) -> str | None` — None passthrough.

ВАЖНО (ADR-0018 §«Production readiness gates»):
- Dev default key `local-dev-key-...` явно проверяется при `environment !=
  'dev'` — fail-loud если случайно попадёт в prod.
- Ключ генерируется один раз при deploy через `Fernet.generate_key()`,
  ротируется ежеквартально.
- Key leak = ПДн compromise; mitigation: SOPS encryption at rest +
  physical safe для backup ключа (ADR-0009 alignment).
"""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from src.api.config import Settings

logger = logging.getLogger(__name__)


# Hardcoded sentinel — Settings default. На production environment'е
# (REHOME_ENV != 'dev' / 'test') этот key strictly запрещён.
_DEV_KEY_SENTINEL = "DnshURO5oCxsHWvw5ECnPe75EVAJTPpv2ImjBOyUZmM="


class HrEncryptionKeyError(RuntimeError):
    """Configuration error: bad / missing / dev-key-in-prod."""


def _build_fernet(settings: Settings) -> MultiFernet:
    """Construct MultiFernet с primary + optional legacy key.

    MultiFernet rotation pattern (per cryptography docs):
    - Encrypts всегда первым ключом (primary).
    - Decrypts перебирая каждый key до success.
    Подходит для rotation transition: новый key primary, старый legacy
    держим до завершения rekey worker'а, потом legacy убирается.
    """
    keys: list[Fernet] = []
    primary = settings.hr_encryption_key

    # Prod gate — dev key never в production (per ADR-0018).
    if settings.environment not in {"dev", "test"} and primary == _DEV_KEY_SENTINEL:
        raise HrEncryptionKeyError(
            "HR_ENCRYPTION_KEY = dev sentinel; production deploys must set "
            "HR_ENCRYPTION_KEY env через `Fernet.generate_key()` output"
        )

    try:
        keys.append(Fernet(primary.encode("ascii")))
    except (ValueError, TypeError) as exc:
        # Fernet требует ровно 32-byte url-safe base64 string. Невалидный
        # format → fail-fast (Settings invariant).
        raise HrEncryptionKeyError(
            "HR_ENCRYPTION_KEY должен быть 32-byte url-safe base64 "
            "(Fernet.generate_key() format)"
        ) from exc

    if settings.hr_encryption_key_legacy is not None:
        try:
            keys.append(Fernet(settings.hr_encryption_key_legacy.encode("ascii")))
        except (ValueError, TypeError) as exc:
            raise HrEncryptionKeyError(
                "HR_ENCRYPTION_KEY_LEGACY invalid format (Fernet expected)"
            ) from exc

    return MultiFernet(keys)


def encrypt_pii(plaintext: str | None, settings: Settings) -> bytes | None:
    """Encrypt single ПДн field. `None` passthrough — preserves
    «не заполнено» semantic.

    Empty string `""` → также None (нормализация: пустая строка ≡
    отсутствие данных для ПДн полей).
    """
    if plaintext is None or plaintext == "":
        return None
    fernet = _build_fernet(settings)
    return fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_pii(ciphertext: bytes | None, settings: Settings) -> str | None:
    """Decrypt ПДн field. `None` passthrough.

    На corrupted ciphertext (InvalidToken) — log warning + return None.
    НЕ raise: corrupted row не должен fail'ить весь list-endpoint. Admin
    UI рендерит «—» для unrecoverable cells.

    Rationale: лучше gracefully degrade чем 500 на весь GET. Audit log
    fired через router'а (decrypt attempt = read event).
    """
    if ciphertext is None:
        return None
    fernet = _build_fernet(settings)
    try:
        return fernet.decrypt(ciphertext).decode("utf-8")
    except InvalidToken:
        logger.warning("hr.pii.decrypt_failed: InvalidToken (key mismatch?)")
        return None


__all__ = [
    "HrEncryptionKeyError",
    "decrypt_pii",
    "encrypt_pii",
]

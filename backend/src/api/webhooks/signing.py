"""HMAC-SHA256 webhook signing (E5.2 #89).

Stripe-like pattern:
- Sender (нас): `hmac_sha256(secret, raw_body) -> hex`. Сетим header
  `X-Rehome-Signature: sha256=<hex>`.
- Receiver (client): берёт raw body как полученный, считает тот же HMAC
  со своим secret, сравнивает constant-time с присланным.

КРИТИЧНО: secret хранится в БД на нашей стороне И у client'а (выдаётся
при POST /webhooks). Compromised secret → возможна подделка events.
Backlog: secret rotation API.
"""

import hashlib
import hmac

SIGNATURE_HEADER = "X-Rehome-Signature"
SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex digest с префиксом `sha256=`.

    `secret` — String (Stripe-like), encode'им utf-8.
    `body` — raw bytes тела request'а (НЕ JSON-объект; сериализация
    делается caller'ом 1 раз для consistency).
    """
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return f"{SIGNATURE_PREFIX}{mac.hexdigest()}"


def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
    """Constant-time проверка подписи (для receiver-side).

    Не используется на нашей стороне (мы — sender), но удобно держать
    рядом для symmetric clients и tests.
    """
    expected = compute_signature(secret, body)
    # `compare_digest` — constant-time, защита от timing attack.
    return hmac.compare_digest(expected, signature_header)

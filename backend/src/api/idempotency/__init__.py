"""Idempotency-Key handling для retry-safety write endpoint'ов.

E5.1 (Issue #44): POST /articles. Cross-cutting модуль; будущий расширение
на PATCH/PUT/DELETE использует те же helpers (E5.x backlog).
"""

from src.api.idempotency.dependency import (
    IdempotencyResult,
    process_idempotency_key,
)
from src.api.idempotency.models import IdempotencyKey
from src.api.idempotency.repository import IdempotencyKeyRepository

__all__ = [
    "IdempotencyKey",
    "IdempotencyKeyRepository",
    "IdempotencyResult",
    "process_idempotency_key",
]

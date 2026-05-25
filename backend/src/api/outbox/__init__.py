"""Transactional outbox для webhook dispatch (#356, ADR-0026).

Slice 0 — foundation: table + repo + drainer worker + dispatcher
env-gated routing. Slice 1+ переводит конкретные business writes
на atomic commit с outbox enqueue в same transaction.
"""

from src.api.outbox.drainer import OutboxDrainer, close_drainer, init_drainer
from src.api.outbox.models import OutboxRow
from src.api.outbox.repository import (
    OutboxRepository,
    get_outbox_repository,
)

__all__ = [
    "OutboxDrainer",
    "OutboxRepository",
    "OutboxRow",
    "close_drainer",
    "get_outbox_repository",
    "init_drainer",
]

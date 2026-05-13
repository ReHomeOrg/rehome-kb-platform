"""Structured logging integration with request-id (#106).

`RequestIdLogFilter` добавляет `record.request_id` поле в каждую LogRecord
из contextvar. Filter применяется к root logger — все child loggers
(включая `rehome.kb.audit`, FastAPI, uvicorn.error) автоматически получат
поле без явной wire-up'ы.

Использование в formatter'е: `%(request_id)s` (если будут JSON-логи —
поле автоматически попадёт в `extra`).
"""

import logging
from typing import Final

from src.api.observability.context import get_request_id

_FILTER_NAME: Final = "request_id_filter"


class RequestIdLogFilter(logging.Filter):
    """Adds `request_id` attribute to LogRecord from contextvar."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        # Return True — filter is for enrichment, not gating.
        return True


def install_request_id_filter() -> None:
    """Attach filter к root logger. Idempotent (повторный вызов no-op).

    Идиомпотентность важна потому что:
    - `pytest` пересоздаёт app per-test иногда → install мог бы дублироваться.
    - Дублирование filter'а не ломает, но дёргает getter дважды per record.
    """
    root = logging.getLogger()
    for existing in root.filters:
        if isinstance(existing, RequestIdLogFilter):
            return
    f = RequestIdLogFilter()
    f.name = _FILTER_NAME
    root.addFilter(f)

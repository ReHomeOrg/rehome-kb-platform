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
    """Attach filter к ВСЕМ existing root handler'ам.

    Python logging spec: `Logger.filter()` НЕ применяется к records от
    child loggers, propagate'ящих в root — только `Handler.filter()`. Поэтому
    filter обязан быть на handler'ах, не на самом root logger'е. Bug
    обнаружен в #111 e2e test'е (chain filter+formatter).

    Idempotent: пропускает handler'ы где filter уже стоит. Если root не
    имеет handler'ов (test isolation) — мы ничего не делаем; в этом случае
    filter добавляется на root logger как fallback (filter'нет records,
    emit'ящиеся напрямую через root.info/error/etc).
    """
    root = logging.getLogger()
    if not root.handlers:
        for existing_logger_filter in root.filters:
            if isinstance(existing_logger_filter, RequestIdLogFilter):
                return
        f = RequestIdLogFilter()
        f.name = _FILTER_NAME
        root.addFilter(f)
        return

    for handler in root.handlers:
        if any(isinstance(hf, RequestIdLogFilter) for hf in handler.filters):
            continue
        f = RequestIdLogFilter()
        f.name = _FILTER_NAME
        handler.addFilter(f)

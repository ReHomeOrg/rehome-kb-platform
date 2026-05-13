"""JSON log formatter для prod log aggregation (#110).

Эмитит одну JSON-line per LogRecord. Поля:
- `timestamp` — ISO8601 UTC.
- `level` — INFO/WARNING/ERROR/etc.
- `logger` — logger name.
- `message` — отформатированное сообщение.
- `request_id` — из contextvar (см. #106).
- `exception` — multi-line traceback в JSON-safe string (если есть).
- Любые user-supplied `extra={...}` ключи — flat в top-level.

Whitelist подход: исключаем internal logging-spec attrs (created, msecs,
relativeCreated, levelno, pathname, filename, module, exc_info, exc_text,
stack_info, lineno, funcName, processName, thread, threadName, process,
args, msg, message, levelname, name) — оставляем только value-add fields.

ФЗ-152: НЕ место для PII фильтрации. Caller (audit/logger sites) уже
compliance'ят payload.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Final

# Стандартные атрибуты LogRecord, не несущие value для JSON-консьюмера.
# Источник: https://docs.python.org/3/library/logging.html#logrecord-attributes
_LOGRECORD_INTERNAL_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        # Output keys — рендерим явно, чтобы порядок и формат были стабильными.
        "request_id",
        "taskName",  # Python 3.12+ asyncio
    }
)


class JsonLogFormatter(logging.Formatter):
    """JSON-line per LogRecord."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            # request_id выставляется RequestIdLogFilter (#106). Default `"-"`
            # если filter не установлен или вызов вне request context.
            "request_id": getattr(record, "request_id", "-"),
        }

        # Extra user-supplied поля (logger.info("...", extra={"foo": "bar"})).
        for key, value in record.__dict__.items():
            if key in _LOGRECORD_INTERNAL_ATTRS or key in payload:
                continue
            payload[key] = value

        if record.exc_info:
            # `formatException` возвращает multi-line traceback string.
            # Кладём в одно JSON-поле — log aggregator'ы парсят как есть.
            payload["exception"] = self.formatException(record.exc_info)

        # `default=str` ловит non-serializable extras (UUID, datetime, etc.)
        # без падения formatter'а.
        return json.dumps(payload, default=str, ensure_ascii=False)


def install_json_log_formatter() -> None:
    """Заменить formatter на root logger's handlers; если handler'ов нет —
    добавить StreamHandler(stderr) с JSON formatter'ом.

    Idempotent: повторный вызов перепринимает formatter (no-op effective)
    но не создаёт duplicate handler'ов.
    """
    root = logging.getLogger()
    formatter = JsonLogFormatter()
    if not root.handlers:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
    else:
        for existing_handler in root.handlers:
            existing_handler.setFormatter(formatter)

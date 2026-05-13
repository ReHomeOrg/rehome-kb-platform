"""ContextVar для request-id propagation (#106).

ContextVar safely переносится через async-границы (`await`, `asyncio.gather`)
в рамках одной задачи — это то что нужно для корреляции логов в FastAPI
request lifecycle.

Sentinel `_NO_REQUEST` отличает "вне request'а" от "в request'е но id ещё
не установлен" — без неё легко получить ложный `None` в логах из shutdown
handler'ов или background задач.
"""

from contextvars import ContextVar
from typing import Final

REQUEST_ID_HEADER: Final = "X-Request-Id"

_NO_REQUEST: Final = "-"

REQUEST_ID_CONTEXT: ContextVar[str] = ContextVar(
    "request_id",
    default=_NO_REQUEST,
)


def get_request_id() -> str:
    """Current request_id, или `"-"` если за пределами request scope."""
    return REQUEST_ID_CONTEXT.get()

"""RequestIdMiddleware (#106).

Pure-ASGI middleware (без BaseHTTPMiddleware — оно ломает StreamingResponse
для SSE). Делает 4 вещи:

1. Читает `X-Request-Id` request header.
2. Если absent / не-UUID — генерирует свежий `uuid4()`.
3. Биндит в `REQUEST_ID_CONTEXT` (contextvar) на время request'а.
4. Эхо'ит в response header `X-Request-Id`.
"""

from typing import Any
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.api.observability.context import REQUEST_ID_CONTEXT, REQUEST_ID_HEADER


def _parse_or_generate(raw: str | None) -> str:
    """Validate UUID format; reject malformed values to fresh `uuid4()`.

    Anti-DoS: не разрешаем клиенту инжектить произвольную строку как
    request-id (log-injection защита: если id попадает в логи как часть
    структурированного поля, инвалидный input — newlines/control chars —
    мог бы ломать парсинг).
    """
    if not raw:
        return str(uuid4())
    try:
        return str(UUID(raw))
    except (ValueError, AttributeError):
        return str(uuid4())


class RequestIdMiddleware:
    """ASGI middleware. Wire via `app.add_middleware(RequestIdMiddleware)`."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Extract incoming header (case-insensitive) → validate or generate.
        header_name = REQUEST_ID_HEADER.lower().encode("latin-1")
        incoming: str | None = None
        for key, value in scope.get("headers", []):
            if key == header_name:
                incoming = value.decode("latin-1", errors="replace")
                break
        request_id = _parse_or_generate(incoming)

        token = REQUEST_ID_CONTEXT.set(request_id)

        async def _send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode("latin-1"), request_id.encode("latin-1")))
                # Cast satisfies starlette's TypedDict; ASGI spec accepts
                # mutable list here.
                new_message: dict[str, Any] = dict(message)
                new_message["headers"] = headers
                await send(new_message)
            else:
                await send(message)

        try:
            await self._app(scope, receive, _send_with_header)
        finally:
            REQUEST_ID_CONTEXT.reset(token)

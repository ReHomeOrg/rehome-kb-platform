"""RequestIdMiddleware (#106).

Pure-ASGI middleware (без BaseHTTPMiddleware — оно ломает StreamingResponse
для SSE). Делает 4 вещи:

1. Читает `X-Request-Id` request header.
2. Если absent / не-UUID — генерирует свежий `uuid4()`.
3. Биндит в `REQUEST_ID_CONTEXT` (contextvar) на время request'а.
4. Эхо'ит в response header `X-Request-Id`.
"""

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

        header_bytes = REQUEST_ID_HEADER.encode("latin-1")

        async def _send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Strip any existing X-Request-Id из downstream handler'а —
                # иначе response может содержать duplicate header (RFC 7230 §3.2.2
                # разрешает только для list-headers; HTTP-клиенты часто берут
                # только первый). Гарантируем single, authoritative value.
                existing = message.get("headers", [])
                deduped = [(k, v) for (k, v) in existing if k.lower() != header_bytes.lower()]
                deduped.append((header_bytes, request_id.encode("latin-1")))
                message["headers"] = deduped  # ASGI Message is MutableMapping.
            await send(message)

        try:
            await self._app(scope, receive, _send_with_header)
        finally:
            REQUEST_ID_CONTEXT.reset(token)

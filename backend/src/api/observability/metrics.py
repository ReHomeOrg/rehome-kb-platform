"""Prometheus metrics + ASGI middleware (#108).

Pull-model: `/metrics` endpoint возвращает text-format snapshot. Prometheus
server опрашивает.

Cardinality discipline: labels — только method/route/status. `route` берётся
из FastAPI route definition (`/api/v1/articles/{slug}`), не raw path —
иначе UUID'ы взрывают cardinality.

Anti-DoS: `/metrics` ДОЛЖЕН быть internal-only. Контроль на reverse proxy
(не публикуется наружу) ИЛИ через `METRICS_ENABLED` env-flag. Этот модуль
не реализует auth — это policy reverse-proxy / network egress.
"""

import time
from typing import Final

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Buckets tuned для web-API (sub-second median, occasional slow tail).
# Default prometheus_client buckets [5,10,...] не подходят — слишком грубо.
_DURATION_BUCKETS: Final = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

REQUESTS_TOTAL: Final = Counter(
    "http_requests_total",
    "Total HTTP requests processed by API gateway.",
    labelnames=("method", "route", "status"),
)

REQUEST_DURATION_SECONDS: Final = Histogram(
    "http_request_duration_seconds",
    "HTTP request handler duration (seconds).",
    labelnames=("method", "route"),
    buckets=_DURATION_BUCKETS,
)


def _resolve_route_path(scope: Scope) -> str:
    """Берёт декларированный путь FastAPI route'а, чтобы UUID/slug'и не
    взрывали cardinality. Fallback на `<unmatched>` если route не resolved
    (404 на unknown path) — single bucket, не утечка path'ов в labels.
    """
    route = scope.get("route")
    if route is None:
        return "<unmatched>"
    return str(getattr(route, "path", "<unmatched>"))


class MetricsMiddleware:
    """ASGI middleware — observes start_time на http.request, status на
    http.response.start, инкрементит counter + observ'ит histogram при
    завершении response'а.

    Pure ASGI (как RequestIdMiddleware) — не ломает SSE/streaming.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        start_time = time.perf_counter()
        status_code: int = 0
        method = str(scope.get("method", "UNKNOWN"))

        async def _send_observing(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 0))
            await send(message)

        try:
            await self._app(scope, receive, _send_observing)
        finally:
            # Route resolves только после того, как FastAPI matched его —
            # на этот момент `scope['route']` populated.
            route_path = _resolve_route_path(scope)
            duration = time.perf_counter() - start_time
            # status=0 → client disconnected до http.response.start. По
            # nginx-конвенции это `499 Client Closed Request` — даёт
            # осмысленную label для алертинга вместо meaningless `"0"`.
            status_label = "499" if status_code == 0 else str(status_code)
            REQUESTS_TOTAL.labels(
                method=method,
                route=route_path,
                status=status_label,
            ).inc()
            REQUEST_DURATION_SECONDS.labels(method=method, route=route_path).observe(duration)


def render_metrics() -> tuple[bytes, str]:
    """Snapshot для GET /metrics handler'а. Возвращает (body, content-type)."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST

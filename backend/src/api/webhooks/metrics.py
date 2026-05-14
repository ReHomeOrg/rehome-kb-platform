"""Prometheus metrics для webhook delivery worker (#174).

Pull-model: worker runs внутри FastAPI lifespan (in-process), метрики
экспортируются через общий `/metrics` endpoint основного приложения
(см. `src/api/observability/metrics.py` middleware).

Metrics:
- `kb_webhook_deliveries_total{event_type, status}` — counter
  попыток доставки. `status ∈ {delivered, failed_network, failed_4xx,
  failed_5xx}`.
- `kb_webhook_delivery_duration_seconds{event_type}` — histogram
  duration POST httpx call (от send до response.received / network
  error).
- `kb_webhook_retries_total{event_type}` — counter retry attempts
  (attempt_no >= 2). На каждый retry incremented один раз.

Cardinality:
- `event_type` — fixed enum из `events.py` (~11 values).
- `status` — fixed enum (4 values).
Итого worst case ~44 series — далеко от прометей-cardinality-bomb.
"""

from typing import Final

from prometheus_client import Counter, Histogram

# Webhook delivery — internet HTTP POST. p50 ~50ms (LAN endpoint),
# p99 может быть 5-10s (cross-region / TLS handshake / SSRF-rejected
# DNS lookup). Buckets cover full range up to timeout.
_DELIVERY_BUCKETS: Final = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)


DELIVERIES_TOTAL: Final = Counter(
    "kb_webhook_deliveries_total",
    "Total webhook delivery attempts grouped by event_type and outcome status.",
    labelnames=("event_type", "status"),
)

DELIVERY_DURATION_SECONDS: Final = Histogram(
    "kb_webhook_delivery_duration_seconds",
    "Webhook HTTP POST duration from send to response/error.",
    labelnames=("event_type",),
    buckets=_DELIVERY_BUCKETS,
)

RETRIES_TOTAL: Final = Counter(
    "kb_webhook_retries_total",
    "Total webhook delivery retry attempts (attempt_no >= 2).",
    labelnames=("event_type",),
)


def classify_status(status_code: int | None) -> str:
    """Map HTTP status / network error → fixed-cardinality bucket.

    `None` = network error (DNS / connect / timeout / TLS).
    2xx → `delivered`; 4xx → `failed_4xx`; 5xx → `failed_5xx`.
    """
    if status_code is None:
        return "failed_network"
    if 200 <= status_code < 300:
        return "delivered"
    if 400 <= status_code < 500:
        return "failed_4xx"
    return "failed_5xx"


__all__ = [
    "DELIVERIES_TOTAL",
    "DELIVERY_DURATION_SECONDS",
    "RETRIES_TOTAL",
    "classify_status",
]

"""Prometheus metrics для popular_query worker (#220).

Pull-model: worker — отдельный process, exposes `/metrics` на HTTP
порту (env `POPULAR_QUERY_METRICS_PORT`, default 9102). Indexer 9100,
vault_reminders 9101, popular_query 9102 чтобы не collide'нуть.

Metrics:
- `kb_popular_query_scan_total` — counter scan iterations.
- `kb_popular_query_scan_errors_total` — counter scan failures.
- `kb_popular_query_dispatch_total` — counter dispatches sent (одно
  событие per scan tick, поэтому ≤ scan_total).
- `kb_popular_query_queries_emitted` — histogram кол-ва queries в
  одном dispatch payload (для tuning min_count).
- `kb_popular_query_scan_duration_seconds` — histogram scan duration
  (group-by aggregate sql + dispatch fan-out).
"""

from typing import Final

from prometheus_client import Counter, Histogram

# Aggregation — GROUP BY на partial index. p50 < 100ms на 100k rows.
# p99 — depends на subscriber count для dispatch fan-out.
_SCAN_BUCKETS: Final = (0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# Number of distinct popular queries per dispatch — typical 0-10.
# Cap'ом max_queries=50, поэтому верхний bucket 50.
_QUERIES_BUCKETS: Final = (0, 1, 3, 5, 10, 20, 50)


SCAN_TOTAL: Final = Counter(
    "kb_popular_query_scan_total",
    "Total scan iterations completed (success or fail).",
)

SCAN_ERRORS_TOTAL: Final = Counter(
    "kb_popular_query_scan_errors_total",
    "Total scan iterations failed with exception.",
)

DISPATCH_TOTAL: Final = Counter(
    "kb_popular_query_dispatch_total",
    "Total search.popular_query webhook dispatches sent (non-empty payloads).",
)

QUERIES_EMITTED: Final = Histogram(
    "kb_popular_query_queries_emitted",
    "Number of distinct popular queries в одном dispatch payload.",
    buckets=_QUERIES_BUCKETS,
)

SCAN_DURATION_SECONDS: Final = Histogram(
    "kb_popular_query_scan_duration_seconds",
    "Duration of a single scan iteration в секундах.",
    buckets=_SCAN_BUCKETS,
)


__all__ = [
    "DISPATCH_TOTAL",
    "QUERIES_EMITTED",
    "SCAN_DURATION_SECONDS",
    "SCAN_ERRORS_TOTAL",
    "SCAN_TOTAL",
]

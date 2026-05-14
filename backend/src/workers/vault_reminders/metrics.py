"""Prometheus metrics для vault_reminders worker (#176).

Pull-model: worker — отдельный process, exposes `/metrics` на HTTP
порту (env `VAULT_REMINDER_METRICS_PORT`, default 9101). Indexer
держит 9100 — здесь 9101 чтобы не collide'нуть при single-node dev.

Metrics:
- `kb_vault_reminders_scan_total` — counter scan iterations
  completed (success or fail).
- `kb_vault_reminders_emitted_total{category}` — counter notifications
  emitted, по `vault_secrets.category` label.
- `kb_vault_reminders_scan_duration_seconds` — histogram scan
  durations (от open session до close).
- `kb_vault_reminders_scan_errors_total` — counter scan iterations
  failed (exception в run_once).

Cardinality:
- `category` — fixed enum в `vault.models` (~10 values: password /
  api_key / cert / etc). Safe.
- No labels на остальных — global aggregates достаточно для single
  worker.
"""

from typing import Final

from prometheus_client import Counter, Histogram

# Scan — DB SELECT с filter на expires_at range. p50 ~50ms, p99
# может быть 1-2s на large vaults без index hint.
_SCAN_BUCKETS: Final = (0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


SCAN_TOTAL: Final = Counter(
    "kb_vault_reminders_scan_total",
    "Total scan iterations completed (success or fail).",
)

EMITTED_TOTAL: Final = Counter(
    "kb_vault_reminders_emitted_total",
    "Total reminder notifications emitted, by secret category.",
    labelnames=("category",),
)

SCAN_DURATION_SECONDS: Final = Histogram(
    "kb_vault_reminders_scan_duration_seconds",
    "Duration of a single scan iteration in seconds.",
    buckets=_SCAN_BUCKETS,
)

SCAN_ERRORS_TOTAL: Final = Counter(
    "kb_vault_reminders_scan_errors_total",
    "Total scan iterations failed with exception.",
)


__all__ = [
    "EMITTED_TOTAL",
    "SCAN_DURATION_SECONDS",
    "SCAN_ERRORS_TOTAL",
    "SCAN_TOTAL",
]

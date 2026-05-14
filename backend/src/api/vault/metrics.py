"""Prometheus metrics для vault module (#180, ADR-0011).

In-process: метрики через общий `/metrics` endpoint.

Zero-knowledge invariant: метрики ОБЯЗАНЫ оперировать только metadata
(category, result, action). Никаких labels с user_id / secret_id /
plaintext — иначе TSDB становится PII store.

Metrics:
- `kb_vault_unlock_total{result}` — unlock attempts, `result ∈
  {success, failed}`. Security forensic: spike в `failed` → bruteforce.
- `kb_vault_secret_access_total{action, category}` — secret access
  events. `action ∈ {created, read, deleted}`. `category` — fixed
  enum (~10 values: password / api_key / cert / token / etc.).

Cardinality:
- `result`: 2 values
- `action`: 3 values
- `category`: ~10 values
- Worst case ~60 series — safe.
"""

from typing import Final

from prometheus_client import Counter

UNLOCK_TOTAL: Final = Counter(
    "kb_vault_unlock_total",
    "Total vault unlock attempts, by result (success/failed).",
    labelnames=("result",),
)

SECRET_ACCESS_TOTAL: Final = Counter(
    "kb_vault_secret_access_total",
    "Total vault secret access events, by action and category.",
    labelnames=("action", "category"),
)


__all__ = [
    "SECRET_ACCESS_TOTAL",
    "UNLOCK_TOTAL",
]

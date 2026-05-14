"""Prometheus metrics для indexer worker (#152).

Pull-model: worker exposes `/metrics` на отдельном HTTP порту (по умолчанию
9100). Prometheus scraper poll'ит. Worker не listens HTTP для бизнес-логики
— этот endpoint single-purpose observability.

Metrics:
- `kb_indexer_articles_processed_total{model_id}` — counter успешно
  indexed articles (≥1 chunk written).
- `kb_indexer_articles_failed_total{model_id, reason}` — counter
  failures (provider_error / upsert_error / unknown).
- `kb_indexer_batch_duration_seconds{model_id}` — histogram batch
  duration (от fetch до commit).
- `kb_indexer_pending_articles` — gauge сколько PUBLISHED articles
  ждут индексации под current model_id.

Cardinality discipline: `model_id` label — низкая кардинальность
(~2-3 значения за весь lifecycle blue-green migration). `reason`
labels — fixed enum.
"""

from typing import Final

from prometheus_client import Counter, Gauge, Histogram

# Buckets: indexer batches вьетнамски от ~100ms (10 chunks * 10ms each)
# до 30s (batch с большими articles + HF encoding).
_BATCH_BUCKETS: Final = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)


ARTICLES_PROCESSED_TOTAL: Final = Counter(
    "kb_indexer_articles_processed_total",
    "Total articles successfully indexed (≥1 chunk written).",
    labelnames=("model_id",),
)

ARTICLES_FAILED_TOTAL: Final = Counter(
    "kb_indexer_articles_failed_total",
    "Total article indexing failures, by reason.",
    labelnames=("model_id", "reason"),
)

BATCH_DURATION_SECONDS: Final = Histogram(
    "kb_indexer_batch_duration_seconds",
    "Batch processing duration (fetch + index + commit).",
    labelnames=("model_id",),
    buckets=_BATCH_BUCKETS,
)

PENDING_ARTICLES: Final = Gauge(
    "kb_indexer_pending_articles",
    "Count of PUBLISHED articles without embeddings under current model_id.",
    labelnames=("model_id",),
)


__all__ = [
    "ARTICLES_FAILED_TOTAL",
    "ARTICLES_PROCESSED_TOTAL",
    "BATCH_DURATION_SECONDS",
    "PENDING_ARTICLES",
]

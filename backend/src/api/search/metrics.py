"""Prometheus metrics для hybrid retrieval (#179).

In-process: метрики экспонируются через общий `/metrics` endpoint основного
FastAPI приложения (см. `src/api/observability/metrics.py`).

Metrics:
- `kb_retrieval_total{has_results}` — counter retrieval calls,
  `has_results ∈ {"yes", "no"}`. `no` = empty result (no chunks match
  query или access_level filter empty).
- `kb_retrieval_duration_seconds` — histogram end-to-end retrieval
  duration (embed + vector query + BM25 query + RRF fuse).
- `kb_retrieval_hits` — histogram количества chunks возвращённых
  (post-RRF). Distribution insight для tuning `top_k` / `per_retriever_k`.

Cardinality: only fixed-cardinality labels (`has_results` 2 values).
"""

from typing import Final

from prometheus_client import Counter, Histogram

# Retrieval = embed (~50ms HF) + vector search (~20ms) + BM25 (~30ms).
# Baseline ~100ms; outliers до 2s при provider slowdown.
_DURATION_BUCKETS: Final = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# Hits — typical 5-10 chunks (DEFAULT_FUSED_TOP_K=10, chat uses 5).
# Bucket 0 captures empty results (already labeled через has_results,
# но histogram для distribution analytics).
_HITS_BUCKETS: Final = (0, 1, 3, 5, 10, 20, 50)


RETRIEVAL_TOTAL: Final = Counter(
    "kb_retrieval_total",
    "Total hybrid retrieval calls, labelled by whether results were found.",
    labelnames=("has_results",),
)

RETRIEVAL_DURATION_SECONDS: Final = Histogram(
    "kb_retrieval_duration_seconds",
    "Hybrid retrieval duration (embed + vector + BM25 + RRF fusion).",
    buckets=_DURATION_BUCKETS,
)

RETRIEVAL_HITS: Final = Histogram(
    "kb_retrieval_hits",
    "Number of chunks returned (post-RRF fusion).",
    buckets=_HITS_BUCKETS,
)


__all__ = [
    "RETRIEVAL_DURATION_SECONDS",
    "RETRIEVAL_HITS",
    "RETRIEVAL_TOTAL",
]

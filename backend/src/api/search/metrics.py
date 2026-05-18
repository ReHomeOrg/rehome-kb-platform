"""Prometheus metrics для hybrid retrieval (#179) + rerank (#217).

In-process: метрики экспонируются через общий `/metrics` endpoint основного
FastAPI приложения (см. `src/api/observability/metrics.py`).

Metrics:
- `kb_retrieval_total{has_results}` — counter retrieval calls,
  `has_results ∈ {"yes", "no"}`. `no` = empty result (no chunks match
  query или access_level filter empty).
- `kb_retrieval_duration_seconds` — histogram end-to-end retrieval
  duration (embed + vector query + BM25 query + RRF fuse + optional rerank).
- `kb_retrieval_hits` — histogram количества chunks возвращённых
  (post-RRF / post-rerank).
- `kb_rerank_total{provider}` — counter rerank invocations,
  `provider ∈ {"mock", "cross_encoder"}`.
- `kb_rerank_duration_seconds{provider}` — histogram cross-encoder
  inference latency (mock — typical <1ms; cross-encoder — 50-200ms).
- `kb_rerank_hits` — histogram количества hits passed через reranker
  (для tuning RERANK_TOP_N).

Cardinality: fixed labels only. `provider` ≤ 2 значения, `has_results` 2.
"""

from typing import Final

from prometheus_client import Counter, Histogram

# Retrieval = embed (~50ms HF) + vector search (~20ms) + BM25 (~30ms).
# Baseline ~100ms; outliers до 2s при provider slowdown.
_DURATION_BUCKETS: Final = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# Rerank duration: mock <1ms, cross-encoder 50-200ms (depends на N + model).
# Outliers до 1-2s при cold model load.
_RERANK_DURATION_BUCKETS: Final = (
    0.001,
    0.005,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
)

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
    "Hybrid retrieval duration (embed + vector + BM25 + RRF fusion + optional rerank).",
    buckets=_DURATION_BUCKETS,
)

RETRIEVAL_HITS: Final = Histogram(
    "kb_retrieval_hits",
    "Number of chunks returned (post-RRF fusion, post-rerank if enabled).",
    buckets=_HITS_BUCKETS,
)

RERANK_TOTAL: Final = Counter(
    "kb_rerank_total",
    "Total rerank invocations, labelled by provider.",
    labelnames=("provider",),
)

RERANK_DURATION_SECONDS: Final = Histogram(
    "kb_rerank_duration_seconds",
    "Reranker inference duration (mock token-overlap or cross-encoder predict).",
    labelnames=("provider",),
    buckets=_RERANK_DURATION_BUCKETS,
)

RERANK_HITS: Final = Histogram(
    "kb_rerank_hits",
    "Number of hits passed through reranker (input size).",
    buckets=_HITS_BUCKETS,
)


__all__ = [
    "RERANK_DURATION_SECONDS",
    "RERANK_HITS",
    "RERANK_TOTAL",
    "RETRIEVAL_DURATION_SECONDS",
    "RETRIEVAL_HITS",
    "RETRIEVAL_TOTAL",
]

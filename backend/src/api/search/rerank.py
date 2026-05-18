"""Cross-encoder re-ranker для RAG retrieval (ADR-0010 follow-up).

Контекст: hybrid RRF (vector + BM25) даёт top-K candidates с rank-based
score'ом. Cross-encoder re-ranker берёт (query, candidate_text) пары и
выдаёт более точный relevance score через bi-encoder → cross-encoder
upgrade. Trade-off: latency растёт (extra inference call), но precision@k
улучшается особенно для long-tail queries.

Применяется ПОВЕРХ RRF: RRF top-N (например 20) → reranker → reorder
→ top-K (например 10). RRF дешёвый recall, cross-encoder — expensive
precision.

Pattern:
- `MockReranker`: детерминистический, для tests / CI / dev. Сортирует
  по простой similarity heuristic (token overlap) без ML.
- `CrossEncoderReranker`: production, `sentence_transformers.CrossEncoder`
  (BAAI/bge-reranker-base или ms-marco-MiniLM-L-6-v2). Heavy deps —
  не загружается в default API container (см. requirements-rag.txt).

Gating через `RERANK_ENABLED=false` default — re-rank off, retrieval
работает как раньше (backward-compat).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Final, Protocol

from src.api.search.repository import RetrievalHit

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    """Async re-rank interface.

    Контракт:
    - Input: (query, list[RetrievalHit]).
    - Output: тот же набор hits, reordered по новому score (descending).
      `RetrievalHit.score` field обновлён на cross-encoder relevance.
    - Idempotent: same input → same output.
    - Empty input → empty output.
    """

    async def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
    ) -> list[RetrievalHit]: ...

    @property
    def model_id(self) -> str:
        """Stable identifier — для logging / debug / metrics."""
        ...


class MockReranker:
    """Deterministic re-ranker для tests / dev.

    Score = доля токенов из query, найденных в hit.text (case-insensitive,
    word boundary). Не качество retrieval'а — это smoke сигнал.
    """

    def __init__(self, model_id: str = "mock-rerank-v1") -> None:
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    async def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
    ) -> list[RetrievalHit]:
        if not hits:
            return []
        query_tokens = {t for t in query.lower().split() if len(t) >= 3}
        if not query_tokens:
            return list(hits)
        scored: list[tuple[float, RetrievalHit]] = []
        for hit in hits:
            text_lower = hit.text.lower()
            matches = sum(1 for t in query_tokens if t in text_lower)
            score = matches / len(query_tokens)
            # Replace fused RRF score → cross-encoder-style score.
            scored.append((score, _hit_with_score(hit, score)))
        scored.sort(key=lambda x: -x[0])
        return [hit for _, hit in scored]


# Singleton cache (analog к embeddings_hf._MODEL_CACHE). CrossEncoder
# instance reused между Depends() invocations — иначе каждый request
# грузил бы model заново.
_CROSS_ENCODER_CACHE: dict[str, Any] = {}
_CROSS_ENCODER_CACHE_LOCK: Final = threading.Lock()


def _load_cross_encoder(model_name: str) -> Any:
    cached = _CROSS_ENCODER_CACHE.get(model_name)
    if cached is not None:
        return cached
    with _CROSS_ENCODER_CACHE_LOCK:
        cached = _CROSS_ENCODER_CACHE.get(model_name)
        if cached is not None:
            return cached
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers not installed for cross-encoder reranker.\n"
                "Install RAG deps:\n"
                "  pip install -r backend/requirements-rag.txt\n"
                "Or set RERANK_PROVIDER=mock for dev/CI."
            ) from exc
        logger.info("rerank.loading_model", extra={"model": model_name})
        instance = CrossEncoder(model_name)
        _CROSS_ENCODER_CACHE[model_name] = instance
        return instance


class CrossEncoderReranker:
    """Production reranker через sentence_transformers.CrossEncoder.

    Default model `BAAI/bge-reranker-base` (~280 MB) — multilingual,
    хорошо работает на русском + английском. Альтернатива
    `cross-encoder/ms-marco-MiniLM-L-6-v2` — меньше (~80MB) но English-only.

    `predict()` — blocking inference; обёрнут в `asyncio.to_thread`.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        # Trigger load (singleton).
        self._model = _load_cross_encoder(model_name)

    @property
    def model_id(self) -> str:
        return self._model_name

    async def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
    ) -> list[RetrievalHit]:
        if not hits:
            return []
        import asyncio

        pairs = [(query, hit.text) for hit in hits]
        scores = await asyncio.to_thread(self._predict_sync, pairs)
        scored = [(float(s), hit) for s, hit in zip(scores, hits, strict=True)]
        scored.sort(key=lambda x: -x[0])
        return [_hit_with_score(hit, score) for score, hit in scored]

    def _predict_sync(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Sync wrapper. Returns raw cross-encoder scores."""
        # CrossEncoder.predict accepts list of (query, doc) tuples → ndarray.
        result = self._model.predict(pairs, convert_to_numpy=True)
        return [float(s) for s in result]


def _hit_with_score(hit: RetrievalHit, score: float) -> RetrievalHit:
    """Return copy of RetrievalHit с обновлённым score (frozen dataclass)."""
    from dataclasses import replace

    return replace(hit, score=score)


__all__ = ["CrossEncoderReranker", "MockReranker", "Reranker"]

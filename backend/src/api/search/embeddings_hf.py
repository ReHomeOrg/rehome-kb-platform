"""HF / sentence-transformers embedding provider (#140).

Production-grade EmbeddingProvider для ADR-0010 Stage 1 RAG. Заменяет
MockProvider в проде (включается через `EMBEDDING_PROVIDER=hf`).

## Deployment topology

Heavy deps (PyTorch ~1.5GB + sentence-transformers + model weights ~2.3GB)
НЕ загружаются в main API container. HF provider используется только в
dedicated indexer worker (отдельный Docker target — follow-up PR);
main FastAPI container запускается с `EMBEDDING_PROVIDER=mock` до полного
прод-cutover'а.

Для local dev / прод-worker:
    pip install -r backend/requirements-rag.txt

## Lazy import + singleton cache

`sentence_transformers` импортируется лениво в `__init__` — если деп не
установлен, ясный `RuntimeError` (не cryptic ImportError при FastAPI
startup'е). Module-level `_MODEL_CACHE` хранит SentenceTransformer
instance — повторное создание `SentenceTransformersEmbeddingProvider`
с тем же model_name reuses already-loaded model. Без cache каждый
`Depends(get_retrieval_service)` грузил бы model заново (~30s + 2.3GB).

## Thread-safety

`SentenceTransformer.encode()` — blocking CPU/GPU call. Wrapped в
`asyncio.to_thread` чтобы не блокировать event loop. Default-loop's
ThreadPoolExecutor sequential per provider — для batch'ей это OK
(encode сам параллелит внутренне).
"""

import asyncio
import logging
import threading
from typing import Any, Final

from src.api.search.models import EMBEDDING_DIM_STAGE1

logger = logging.getLogger(__name__)

# `Any` — sentence_transformers может быть not-installed; lazy.
_MODEL_CACHE: dict[str, Any] = {}
_MODEL_CACHE_LOCK: Final = threading.Lock()


def _load_model(model_name: str) -> Any:
    """Get cached SentenceTransformer instance или загрузить новый.

    Thread-safe через lock: первый caller грузит, последующие ждут
    (`SentenceTransformer.__init__` — non-reentrant в HF impl).
    """
    cached = _MODEL_CACHE.get(model_name)
    if cached is not None:
        return cached
    with _MODEL_CACHE_LOCK:
        # Double-check после lock acquire.
        cached = _MODEL_CACHE.get(model_name)
        if cached is not None:
            return cached
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers not installed. Install RAG deps:\n"
                "  pip install -r backend/requirements-rag.txt\n"
                "Or set EMBEDDING_PROVIDER=mock for dev/CI."
            ) from exc
        logger.info("hf_provider.loading_model", extra={"model": model_name})
        instance = SentenceTransformer(model_name)
        _MODEL_CACHE[model_name] = instance
        return instance


class SentenceTransformersEmbeddingProvider:
    """Production EmbeddingProvider via sentence-transformers.

    Default model `intfloat/multilingual-e5-large` (1024-dim) —
    multilingual-friendly для русского + английского. `model_id` для
    DB column = model_name as-is (blue-green re-embedding key).
    """

    def __init__(self, model_name: str, dim: int = EMBEDDING_DIM_STAGE1) -> None:
        self._model_name = model_name
        self._dim = dim
        # Trigger load (singleton). Fail-fast в DI / startup, а не
        # на первом chat-message.
        self._model = _load_model(model_name)

    @property
    def model_id(self) -> str:
        return self._model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Blocking encode → offload в default executor чтобы не
        # блокировать event loop.
        return await asyncio.to_thread(self._encode_sync, texts)

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Sync wrapper над SentenceTransformer.encode для to_thread.

        `normalize_embeddings=True` — приводит vectors к unit norm
        (cosine similarity ≡ dot product, что matches pgvector `<=>`
        operator семантику).
        """
        # `Any`-typed model — runtime call OK; mypy не trip'нется
        # на отсутствующем sentence_transformers stub.
        result = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        # numpy ndarray → list[list[float]]. `.tolist()` рекурсивно.
        out: list[list[float]] = result.tolist()
        # Defensive dim check — model output должен matchить config.
        if out and len(out[0]) != self._dim:
            raise RuntimeError(
                f"Model {self._model_name} produced dim {len(out[0])}, "
                f"expected {self._dim}. Check EMBEDDING_DIM env vs model output."
            )
        return out

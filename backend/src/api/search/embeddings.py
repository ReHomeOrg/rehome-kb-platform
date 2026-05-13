"""EmbeddingProvider interface + Mock impl (kb-search Stage 1, #128).

`EmbeddingProvider` Protocol — single async method `embed(texts)` →
list of float vectors. Real implementation
(`SentenceTransformersEmbeddingProvider`) — отдельный PR с indexer
worker, потому что требует ~2 GB PyTorch / transformers deps и model
weights download.

`MockEmbeddingProvider` — deterministic vectors based на hash(text).
Используется unit tests + dev environments когда real model unavailable.
Производит valid `EMBEDDING_DIM_STAGE1`-length vectors (1024).
"""

import hashlib
import struct
from typing import Final, Protocol

from src.api.search.models import EMBEDDING_DIM_STAGE1

# Signed int32 range (`<i` unpack) — normalize в [-1.0, 1.0).
_INT32_MAX_PLUS_1: Final = 2**31

_DEFAULT_MOCK_MODEL_ID: Final = "mock-v1"


class EmbeddingProvider(Protocol):
    """Async batch embedding interface.

    Implementations:
    - `MockEmbeddingProvider` — для tests / dev (этот файл).
    - `SentenceTransformersEmbeddingProvider` — production
      (отдельный PR; loads `intfloat/multilingual-e5-large`).

    Контракт `embed`:
    - Input: list of non-empty strings.
    - Output: list of same length, каждый вектор — `EMBEDDING_DIM_STAGE1`
      float'ов в [-1, 1] диапазоне (cosine similarity friendly).
    - Не должен mutate'ить input.
    - Idempotent: same input → same output.
    """

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def model_id(self) -> str:
        """Stable identifier for этой instance'ы провайдера. Используется в
        `embedding_model_id` column для blue-green re-embedding."""
        ...


class MockEmbeddingProvider:
    """Deterministic mock for tests / dev.

    Hash-based generation: SHA-256 over text, expanded до `EMBEDDING_DIM`
    через repeating + normalizing. Same text → same vector exactly.
    Different texts → different vectors (collision-resistant per SHA-256).
    """

    def __init__(
        self,
        model_id: str = _DEFAULT_MOCK_MODEL_ID,
        dim: int = EMBEDDING_DIM_STAGE1,
    ) -> None:
        self._model_id = model_id
        self._dim = dim

    @property
    def model_id(self) -> str:
        return self._model_id

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        # Расширяем 32-byte SHA-256 → `dim` floats через repeating SHA с
        # incremented counter. 4 bytes per float (signed int32 → /MAX*2 - 1
        # для [-1, 1] range).
        result: list[float] = []
        counter = 0
        while len(result) < self._dim:
            seed = f"{counter}:{text}".encode()
            digest = hashlib.sha256(seed).digest()
            # 8 floats per 32-byte digest.
            for i in range(0, 32, 4):
                if len(result) >= self._dim:
                    break
                (n,) = struct.unpack("<i", digest[i : i + 4])
                # Normalize signed int32 → [-1.0, 1.0).
                result.append(n / _INT32_MAX_PLUS_1)
            counter += 1
        return result[: self._dim]

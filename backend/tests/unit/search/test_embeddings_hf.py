"""Unit tests for SentenceTransformersEmbeddingProvider (#140).

Tests skipped целиком если `sentence_transformers` не установлен (CI
default не содержит RAG deps — см. requirements-rag.txt). На local /
prod worker'е, где деп есть, tests load actual model и валидируют
behavior.
"""

import pytest

# Module-level skip — все tests требуют sentence_transformers + ~30s
# model load. CI без RAG deps пропустит.
pytest.importorskip("sentence_transformers")

from src.api.search.embeddings_hf import (  # noqa: E402
    SentenceTransformersEmbeddingProvider,
    _load_model,
)

# Маленькая HF модель для быстрых tests — paraphrase-MiniLM-L6-v2 (~80MB
# vs ~2.3GB для production multilingual-e5-large). 384-dim — НЕ matches
# `EMBEDDING_DIM_STAGE1=1024`, поэтому конструктор должен принять
# explicit `dim` параметр.
_TEST_MODEL = "sentence-transformers/paraphrase-MiniLM-L6-v2"
_TEST_DIM = 384


@pytest.fixture(scope="module")
def hf_provider() -> SentenceTransformersEmbeddingProvider:
    """Singleton provider — model load happens once per test module."""
    return SentenceTransformersEmbeddingProvider(model_name=_TEST_MODEL, dim=_TEST_DIM)


def test_model_id_matches_constructor(
    hf_provider: SentenceTransformersEmbeddingProvider,
) -> None:
    """`model_id` = constructor arg (важно для blue-green re-embedding)."""
    assert hf_provider.model_id == _TEST_MODEL


@pytest.mark.asyncio
async def test_embed_returns_list_of_correct_dim(
    hf_provider: SentenceTransformersEmbeddingProvider,
) -> None:
    vectors = await hf_provider.embed(["hello world"])
    assert len(vectors) == 1
    assert len(vectors[0]) == _TEST_DIM
    assert all(isinstance(v, float) for v in vectors[0])


@pytest.mark.asyncio
async def test_embed_batch(
    hf_provider: SentenceTransformersEmbeddingProvider,
) -> None:
    vectors = await hf_provider.embed(["one", "two", "three"])
    assert len(vectors) == 3
    assert all(len(v) == _TEST_DIM for v in vectors)


@pytest.mark.asyncio
async def test_embed_empty_returns_empty(
    hf_provider: SentenceTransformersEmbeddingProvider,
) -> None:
    """[] → [] (не вызывает encode на пустом input)."""
    assert await hf_provider.embed([]) == []


@pytest.mark.asyncio
async def test_embed_deterministic(
    hf_provider: SentenceTransformersEmbeddingProvider,
) -> None:
    """Same text → identical vector (HF deterministic в eval mode)."""
    a = await hf_provider.embed(["sample"])
    b = await hf_provider.embed(["sample"])
    assert a == b


@pytest.mark.asyncio
async def test_embed_distinct_texts_distinct_vectors(
    hf_provider: SentenceTransformersEmbeddingProvider,
) -> None:
    """Разные тексты → разные vectors (collision-resistant)."""
    [va, vb] = await hf_provider.embed(["foo", "bar baz qux"])
    assert va != vb


def test_load_model_caches_singleton() -> None:
    """`_load_model` reuses instance для same model_name."""
    m1 = _load_model(_TEST_MODEL)
    m2 = _load_model(_TEST_MODEL)
    assert m1 is m2


@pytest.mark.asyncio
async def test_embed_normalized_to_unit_norm(
    hf_provider: SentenceTransformersEmbeddingProvider,
) -> None:
    """`normalize_embeddings=True` → ||vector|| == 1 (cosine sim ≡ dot)."""
    [v] = await hf_provider.embed(["test"])
    norm_sq = sum(x * x for x in v)
    assert abs(norm_sq - 1.0) < 1e-3  # float32 precision


@pytest.mark.asyncio
async def test_embed_dim_mismatch_raises() -> None:
    """Если configured dim != model output dim → RuntimeError fail-fast."""
    bad = SentenceTransformersEmbeddingProvider(model_name=_TEST_MODEL, dim=_TEST_DIM + 1)
    with pytest.raises(RuntimeError, match="produced dim"):
        await bad.embed(["x"])

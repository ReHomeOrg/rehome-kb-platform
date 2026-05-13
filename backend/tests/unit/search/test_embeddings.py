"""Unit tests для MockEmbeddingProvider (#128)."""

import pytest

from src.api.search.embeddings import MockEmbeddingProvider
from src.api.search.models import EMBEDDING_DIM_STAGE1


@pytest.mark.asyncio
async def test_embed_returns_correct_shape() -> None:
    p = MockEmbeddingProvider()
    vectors = await p.embed(["hello", "world"])
    assert len(vectors) == 2
    for v in vectors:
        assert len(v) == EMBEDDING_DIM_STAGE1
        assert all(isinstance(x, float) for x in v)


@pytest.mark.asyncio
async def test_embed_deterministic() -> None:
    """Same input → same output (idempotent contract)."""
    p = MockEmbeddingProvider()
    v1 = (await p.embed(["test text"]))[0]
    v2 = (await p.embed(["test text"]))[0]
    assert v1 == v2


@pytest.mark.asyncio
async def test_different_inputs_different_outputs() -> None:
    """Different inputs → different vectors (collision-resistant)."""
    p = MockEmbeddingProvider()
    v1 = (await p.embed(["text A"]))[0]
    v2 = (await p.embed(["text B"]))[0]
    assert v1 != v2


@pytest.mark.asyncio
async def test_embed_does_not_mutate_input() -> None:
    p = MockEmbeddingProvider()
    inp = ["a", "b", "c"]
    inp_copy = list(inp)
    await p.embed(inp)
    assert inp == inp_copy


def test_model_id_is_property() -> None:
    p = MockEmbeddingProvider(model_id="custom-id")
    assert p.model_id == "custom-id"


def test_default_model_id() -> None:
    p = MockEmbeddingProvider()
    assert p.model_id == "mock-v1"


@pytest.mark.asyncio
async def test_vector_values_in_unit_range() -> None:
    """Float values [-1.0, 1.0) для cosine similarity friendliness."""
    p = MockEmbeddingProvider()
    v = (await p.embed(["sample"]))[0]
    assert all(-1.0 <= x < 1.0 for x in v)


@pytest.mark.asyncio
async def test_empty_batch() -> None:
    p = MockEmbeddingProvider()
    assert await p.embed([]) == []

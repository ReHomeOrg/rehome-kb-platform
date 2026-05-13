"""Unit tests для ArticleEmbedding ORM (kb-search Stage 1 foundation, #126)."""

from uuid import uuid4

from src.api.search.models import ArticleEmbedding


def test_article_embedding_construction() -> None:
    """ORM-объект конструируется с обязательными полями."""
    e = ArticleEmbedding(
        article_id=uuid4(),
        chunk_index=0,
        embedding_model_id="intfloat/multilingual-e5-large",
        embedding=[0.1] * 1024,
        char_start=0,
        char_end=512,
    )
    assert e.chunk_index == 0
    assert e.embedding_model_id == "intfloat/multilingual-e5-large"
    assert len(e.embedding) == 1024


def test_article_embedding_table_registered() -> None:
    """Model импортируется через models_all и попадает в Base.metadata."""
    from src.api.db.base import Base
    from src.api.db.models_all import ArticleEmbedding as ArticleEmbeddingFromAll

    # Same class (single source).
    assert ArticleEmbeddingFromAll is ArticleEmbedding
    # Table зарегистрирована.
    assert "article_embeddings" in Base.metadata.tables


def test_article_embedding_table_args() -> None:
    """`__table_args__` содержит comment."""
    from src.api.db.base import Base

    table = Base.metadata.tables["article_embeddings"]
    assert "ADR-0010" in (table.comment or "")

"""kb-search module — RAG retrieval (ADR-0010, #126).

Stage 1: pgvector в существующем Postgres-kb. Этот PR landed foundation
(schema + models). Follow-up PR'ы добавят:
- Chunker (paragraph-based).
- EmbeddingProvider (sentence-transformers wrapper + Mock).
- Indexer worker (article webhook event → chunk → embed → upsert).
- Repository (upsert/delete_by_article/query).
- Hybrid retrieval (BM25 + vector + RRF).
- Endpoint POST /api/v1/search/articles.
- Chat module integration.
"""

from src.api.search.chunker import Chunk, chunk_text
from src.api.search.embeddings import EmbeddingProvider, MockEmbeddingProvider
from src.api.search.models import EMBEDDING_DIM_STAGE1, ArticleEmbedding
from src.api.search.repository import EmbeddingRepository, get_embedding_repository

__all__ = [
    "ArticleEmbedding",
    "Chunk",
    "EMBEDDING_DIM_STAGE1",
    "EmbeddingProvider",
    "EmbeddingRepository",
    "MockEmbeddingProvider",
    "chunk_text",
    "get_embedding_repository",
]

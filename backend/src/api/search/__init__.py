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
from src.api.search.indexer import IndexerService, get_indexer_service
from src.api.search.models import EMBEDDING_DIM_STAGE1, ArticleEmbedding
from src.api.search.repository import (
    EmbeddingRepository,
    RetrievalHit,
    get_embedding_repository,
)
from src.api.search.retrieval import RetrievalService, get_retrieval_service
from src.api.search.router import router as search_router
from src.api.search.schemas import SearchHit, SearchInput, SearchResponse

__all__ = [
    "ArticleEmbedding",
    "Chunk",
    "EMBEDDING_DIM_STAGE1",
    "EmbeddingProvider",
    "EmbeddingRepository",
    "IndexerService",
    "MockEmbeddingProvider",
    "RetrievalHit",
    "RetrievalService",
    "SearchHit",
    "SearchInput",
    "SearchResponse",
    "chunk_text",
    "get_embedding_repository",
    "get_indexer_service",
    "get_retrieval_service",
    "search_router",
]

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

from src.api.search.models import ArticleEmbedding

__all__ = ["ArticleEmbedding"]

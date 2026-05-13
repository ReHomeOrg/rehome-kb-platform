"""IndexerService — chunker + embedder + repository pipeline (#130).

Chains components landed в #128 в single `index_article` action:
1. `chunk_text(body_markdown)` → list[Chunk].
2. `provider.embed([c.text for c in chunks])` → list[list[float]].
3. `repo.upsert(article_id, chunks, embeddings, provider.model_id)`.

Article router зовёт `indexer.index_article(...)` синхронно в request
handler'е после repo commit. Mock provider deterministic + fast
(SHA-256 hash expansion, <1ms на chunk) — latency penalty negligible.

`RAG_ENABLED=False` → router skips call (no-op). Default OFF.

Real `SentenceTransformersEmbeddingProvider` для prod deploy'ится
отдельно (ADR-0010 §"Embedding worker hosting"): отдельный k8s
Deployment subscribed на webhook events, не in-process в gateway.

Errors во время index'ирования логируются + swallowed: article
already created (тот transaction уже commit'нулся в article repo),
indexing failure НЕ должна fail'ить request пользователя. Real worker
deployment имеет retry policy.

NB ADR-0003 split responsibility: write-side НЕ enforce'ит
access_level. См. `repository.py` docstring.
"""

import logging
from uuid import UUID

from fastapi import Depends

from src.api.search.chunker import chunk_text
from src.api.search.embeddings import EmbeddingProvider, MockEmbeddingProvider
from src.api.search.repository import EmbeddingRepository, get_embedding_repository

logger = logging.getLogger(__name__)


class IndexerService:
    """Async indexer для article embeddings.

    Provider injected — gateway по умолчанию использует MockProvider (быстрый,
    deterministic). Real model инжектится в отдельном embedding worker
    deployment (ADR-0010 §"Embedding worker hosting").
    """

    def __init__(
        self,
        repository: EmbeddingRepository,
        provider: EmbeddingProvider,
    ) -> None:
        self._repo = repository
        self._provider = provider

    async def index_article(
        self,
        *,
        article_id: UUID,
        body_markdown: str,
    ) -> int:
        """Chunk + embed + upsert. Returns count chunks indexed.

        Empty body → no chunks → 0 (no upsert). Replay-safe (upsert
        ON CONFLICT — re-index того же article overwrites).
        """
        chunks = chunk_text(body_markdown)
        if not chunks:
            logger.info(
                "indexer.empty_body_skipped",
                extra={"article_id": str(article_id)},
            )
            return 0

        texts = [c.text for c in chunks]
        try:
            embeddings = await self._provider.embed(texts)
        except Exception:
            # Provider failure — log + bail. Каll-site fire-and-forget
            # уже игнорирует exception, но мы хотим structured log.
            logger.exception(
                "indexer.embed_failed",
                extra={
                    "article_id": str(article_id),
                    "model_id": self._provider.model_id,
                    "chunk_count": len(chunks),
                },
            )
            return 0

        try:
            n = await self._repo.upsert(
                article_id=article_id,
                chunks=chunks,
                embeddings=embeddings,
                model_id=self._provider.model_id,
            )
            logger.info(
                "indexer.indexed",
                extra={
                    "article_id": str(article_id),
                    "model_id": self._provider.model_id,
                    "chunk_count": n,
                },
            )
            return n
        except Exception:
            logger.exception(
                "indexer.upsert_failed",
                extra={
                    "article_id": str(article_id),
                    "model_id": self._provider.model_id,
                },
            )
            return 0

    async def remove_article(self, article_id: UUID) -> int:
        """Remove all embeddings одной статьи (любой model_id).

        Используется на article archive (DELETE). Под soft-delete pattern:
        FK CASCADE срабатывает только при hard delete; soft-delete (status
        ARCHIVED) НЕ trigger'ит CASCADE — нужно явное remove.
        """
        try:
            n = await self._repo.delete_by_article(article_id)
            logger.info(
                "indexer.removed",
                extra={"article_id": str(article_id), "deleted": n},
            )
            return n
        except Exception:
            logger.exception(
                "indexer.remove_failed",
                extra={"article_id": str(article_id)},
            )
            return 0

    async def remove_article_by_slug(self, slug: str) -> int:
        """Same as `remove_article`, но resolve'ит по slug. Используется
        archive_article handler'ом — repo.archive не возвращает id."""
        try:
            n = await self._repo.delete_by_article_slug(slug)
            logger.info(
                "indexer.removed_by_slug",
                extra={"slug": slug, "deleted": n},
            )
            return n
        except Exception:
            logger.exception("indexer.remove_failed", extra={"slug": slug})
            return 0


def get_indexer_service(
    repo: EmbeddingRepository = Depends(get_embedding_repository),
) -> IndexerService:
    """FastAPI dependency — IndexerService с default MockProvider.

    Real provider injection — отдельный embedding worker deployment
    (ADR-0010). В gateway по-прежнему Mock; реальные vectors live ones
    создаёт separate process'ом.
    """
    return IndexerService(repo, MockEmbeddingProvider())

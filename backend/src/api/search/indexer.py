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
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends

from src.api.config import Settings, get_settings
from src.api.search.chunker import chunk_text
from src.api.search.embeddings import EmbeddingProvider
from src.api.search.repository import EmbeddingRepository, get_embedding_repository

logger = logging.getLogger(__name__)

# Callback (processed_count, last_indexed_chunks) — для progress reporting.
ProgressCallback = Callable[[int, int], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ReindexResult:
    """Result of `IndexerService.reindex_all_articles` (#240)."""

    articles_processed: int
    chunks_total: int
    errors_total: int


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
            # Provider failure — log + bail. Call-site fire-and-forget
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

    async def reindex_all_articles(
        self,
        article_iter: AsyncIterator[tuple[UUID, str]],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> ReindexResult:
        """Iterate over all PUBLISHED articles + reindex каждую (#240).

        Caller-supplied async iterator (typically
        `ArticleRepository.iter_published_for_reindex`) — keep IndexerService
        free от ArticleRepository import cycle.

        Per-article failures swallowed inside `index_article` (already
        logs); reindex_all считает chunks_total / errors_total и продолжает.

        `on_progress(processed, last_indexed_count)` — optional callback
        для admin_task progress update'ов. Если raise — пропадает (we
        don't fail bulk operation на progress reporter glitch).

        Sync execution: на N articles стоимость ~ N × embed_latency_ms.
        В dev/CI обычно < 100 articles → 5s OK. Production volume —
        backlog (Dramatiq worker для off-request execution).
        """
        articles_processed = 0
        chunks_total = 0
        errors_total = 0
        async for article_id, body in article_iter:
            try:
                n = await self.index_article(article_id=article_id, body_markdown=body)
                chunks_total += n
            except Exception:
                logger.exception(
                    "indexer.reindex_all.per_article_failed",
                    extra={"article_id": str(article_id)},
                )
                errors_total += 1
            articles_processed += 1
            if on_progress is not None:
                try:
                    await on_progress(articles_processed, n if errors_total == 0 else 0)
                except Exception:
                    logger.exception("indexer.reindex_all.progress_callback_failed")
        logger.info(
            "indexer.reindex_all.completed",
            extra={
                "articles_processed": articles_processed,
                "chunks_total": chunks_total,
                "errors_total": errors_total,
            },
        )
        return ReindexResult(
            articles_processed=articles_processed,
            chunks_total=chunks_total,
            errors_total=errors_total,
        )


def get_indexer_service(
    repo: EmbeddingRepository = Depends(get_embedding_repository),
    settings: Settings = Depends(get_settings),
) -> IndexerService:
    """FastAPI dependency — IndexerService с settings-driven provider.

    Indexer и retrieval ОБЯЗАНЫ использовать тот же provider (одинаковый
    `model_id` — иначе search по индексу model_id'а вернёт пустоту).
    Общее настройка через `EMBEDDING_PROVIDER` гарантирует это.
    """
    # Lazy import — избегаем circular import retrieval ↔ indexer.
    from src.api.search.retrieval import _build_provider

    return IndexerService(repo, _build_provider(settings))

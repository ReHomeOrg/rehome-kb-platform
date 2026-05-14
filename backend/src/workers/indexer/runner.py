"""IndexerWorker runner (#149, ADR-0010 §Stage 1 deployment topology).

Stand-alone worker process — НЕ часть gateway request lifecycle. Запускается
в отдельном Docker контейнере с heavy RAG deps (sentence-transformers +
PyTorch ~3.8GB). Gateway работает с `EMBEDDING_PROVIDER=mock` пока
worker'ов coverage не достигнет 100%.

Polling-based design (MVP): каждые `poll_interval_seconds` worker
выбирает PUBLISHED articles, у которых нет embeddings под текущим
`provider.model_id`, и индексирует batch'ем. Production может перейти
на event-driven через Postgres LISTEN/NOTIFY или Dramatiq queue —
defer.

Blue-green re-embedding: provider.model_id меняется через env. Worker
автоматически переиндексирует все articles под новым model_id, не
трогая existing rows под старым (PK includes model_id — параллельные
ряды).

Graceful shutdown: SIGTERM / SIGINT triggers stop flag; current
batch завершается, потом process exits cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from sqlalchemy import and_, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import Article
from src.api.search.indexer import IndexerService
from src.api.search.models import ArticleEmbedding
from src.api.search.repository import EmbeddingRepository

logger = logging.getLogger(__name__)

# Session-context factory: каждый batch начинает новую транзакцию.
SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class IndexerWorker:
    """Polling worker для embedding index'а PUBLISHED articles."""

    def __init__(
        self,
        *,
        session_factory: SessionContextFactory,
        make_indexer: Callable[[AsyncSession], IndexerService],
        batch_size: int = 10,
        poll_interval_seconds: float = 30.0,
    ) -> None:
        """`make_indexer(session)` строит IndexerService с repo, bound
        к данной session. Session живёт строго в run_once для атомарности
        batch'а."""
        self._session_factory = session_factory
        self._make_indexer = make_indexer
        self._batch_size = batch_size
        self._poll_interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._model_id_hint: str | None = None  # для start log

    def request_stop(self) -> None:
        """Graceful shutdown — current batch finish'нется, loop exit."""
        logger.info("indexer_worker.stop_requested")
        self._stop_event.set()

    async def run_forever(self) -> None:
        """Main loop: poll, process batch, sleep, repeat.

        Exceptions внутри batch'а логгируются и не валят process —
        следующий poll попробует снова (idempotent upsert).
        """
        logger.info(
            "indexer_worker.start",
            extra={
                "batch_size": self._batch_size,
                "poll_interval_seconds": self._poll_interval,
            },
        )
        while not self._stop_event.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                logger.exception("indexer_worker.batch_failed")
                processed = 0
            if processed == 0:
                # Idle wait — нет работы. Прерываем sleep если stop.
                # Timeout — expected idle path (sleep complete).
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._poll_interval,
                    )
            # Если processed > 0 — сразу следующая итерация (backlog drain).

        logger.info("indexer_worker.stopped")

    async def run_once(self) -> int:
        """Один batch tick. Returns count articles processed."""
        async with self._session_factory() as session:
            indexer = self._make_indexer(session)
            pending = await self._fetch_pending_articles(session, indexer)
            if not pending:
                return 0
            processed = 0
            for article_id, body_markdown in pending:
                try:
                    n = await indexer.index_article(
                        article_id=article_id,
                        body_markdown=body_markdown,
                    )
                    if n > 0:
                        processed += 1
                except Exception:
                    logger.exception(
                        "indexer_worker.article_failed",
                        extra={"article_id": str(article_id)},
                    )
            await session.commit()
            logger.info(
                "indexer_worker.batch_done",
                extra={"processed": processed, "total_pending": len(pending)},
            )
            return processed

    async def _fetch_pending_articles(
        self,
        session: AsyncSession,
        indexer: IndexerService,
    ) -> list[tuple[UUID, str]]:
        """PUBLISHED articles без embeddings под текущим model_id."""
        current_model = indexer._provider.model_id
        embedding_exists = (
            select(1)
            .where(
                and_(
                    ArticleEmbedding.article_id == Article.id,
                    ArticleEmbedding.embedding_model_id == current_model,
                )
            )
            .exists()
        )
        # Article.status='ARCHIVED' — soft-delete индикатор (нет
        # отдельного archived_at column'а в Article model'и). Skip'аем
        # автоматически через status='PUBLISHED' filter.
        stmt = (
            select(Article.id, Article.body_markdown)
            .where(
                Article.status == "PUBLISHED",
                not_(embedding_exists),
            )
            .order_by(Article.updated_at.asc())
            .limit(self._batch_size)
        )
        result = await session.execute(stmt)
        return [(row.id, row.body_markdown) for row in result]


def make_default_indexer(
    provider: object,
) -> Callable[[AsyncSession], IndexerService]:
    """Helper: factory создающая IndexerService(session-bound repo, provider).

    Provider — singleton (model load expensive). Repo создаётся per
    session внутри factory.
    """

    def _factory(session: AsyncSession) -> IndexerService:
        repo = EmbeddingRepository(session)
        return IndexerService(repo, provider)  # type: ignore[arg-type]

    return _factory


def install_signal_handlers(loop: asyncio.AbstractEventLoop, worker: IndexerWorker) -> None:
    """SIGTERM/SIGINT → graceful shutdown.

    Linux signal handlers — best-effort на Windows. Для k8s POD
    termination это критично: до preStop timeout pod SIGTERM'ом
    говорит worker'у "wrap up".
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows / некоторые контейнерные runtime'ы могут не поддерживать
        # signal handlers на event loop — defensive suppress.
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, worker.request_stop)


# Re-export сигнатур для разработчика.
__all__ = [
    "IndexerWorker",
    "SessionContextFactory",
    "install_signal_handlers",
    "make_default_indexer",
]

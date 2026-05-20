"""AdminTaskRunner — asyncio.create_task spawn pattern (#268, ADR-0020 B).

Pattern (similar to WebhookDeliveryWorker в #174):
- Request handler creates task row (status=PENDING), spawns via
  `runner.spawn_*(task_id, ...)`, returns 202 immediately.
- Background coroutine opens own DB session через session_factory,
  выполняет work, marks COMPLETED / FAILED, commits.
- On unhandled exception — logged + marked FAILED via fresh session
  (defensive: outer session may be poisoned).

Crash recovery: app restart → tasks застрянут в RUNNING/PENDING. Reaper
(`task_reaper.py`) cleans их up на lifespan startup (15-min stale window).

Init: `init_runner(session_factory, settings)` called в `main.py` lifespan
exactly once. `get_admin_task_runner()` FastAPI dependency возвращает
singleton — overridable в тестах через `app.dependency_overrides`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from src.api.admin.tasks_repository import AdminTaskRepository
from src.api.articles.repository import ArticleRepository
from src.api.chat.llm.mock import MockProvider
from src.api.search.indexer import IndexerService
from src.api.search.repository import EmbeddingRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.api.admin.eval_runs_schemas import EvalRunProviderResult
    from src.api.config import Settings

logger = logging.getLogger(__name__)


class AdminTaskRunner:
    """asyncio.create_task spawn для admin_tasks (#268, ADR-0020 B)."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[Any],
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    # -----------------------------------------------------------------
    # Reindex

    def spawn_reindex(
        self,
        task_id: UUID,
        scope: str,
        actor_sub: str,
    ) -> asyncio.Task[None]:
        """Spawn background coroutine. Returns Task — caller обычно не
        await'ит (fire-and-forget).
        """
        return asyncio.create_task(
            self._run_reindex(task_id, scope, actor_sub),
            name=f"admin_task_reindex_{task_id}",
        )

    async def _run_reindex(
        self,
        task_id: UUID,
        scope: str,
        actor_sub: str,
    ) -> None:
        async with self._session_factory() as session:
            task_repo = AdminTaskRepository(session)
            try:
                await task_repo.mark_running(task_id)
                if scope in ("all", "articles"):
                    article_repo = ArticleRepository(session)
                    indexer = _build_indexer(session)
                    result = await indexer.reindex_all_articles(
                        article_repo.iter_published_for_reindex(),
                    )
                    if result.articles_processed == 0 and result.errors_total > 0:
                        await task_repo.mark_failed(
                            task_id,
                            error=f"{result.errors_total} article(s) failed to reindex",
                        )
                        await session.commit()
                        return
                # Other scopes — honest stub (no indexer); just COMPLETED.
                await task_repo.mark_completed(task_id)
                await session.commit()
            except Exception as exc:
                logger.exception(
                    "admin_task.reindex.failed",
                    extra={"task_id": str(task_id), "scope": scope, "actor_sub": actor_sub},
                )
                await session.rollback()
                await self._mark_failed_isolated(task_id, str(exc))

    # -----------------------------------------------------------------
    # Audit-log export

    def spawn_audit_export(
        self,
        task_id: UUID,
        result_url: str,
        actor_sub: str,
    ) -> asyncio.Task[None]:
        return asyncio.create_task(
            self._run_audit_export(task_id, result_url, actor_sub),
            name=f"admin_task_audit_export_{task_id}",
        )

    async def _run_audit_export(
        self,
        task_id: UUID,
        result_url: str,
        actor_sub: str,
    ) -> None:
        async with self._session_factory() as session:
            task_repo = AdminTaskRepository(session)
            try:
                await task_repo.mark_running(task_id)
                # Export — no actual blob storage в MVP; result_url already
                # built by caller. Task instantly transitions to COMPLETED
                # после bookkeeping.
                await task_repo.mark_completed(task_id, result_url=result_url)
                await session.commit()
            except Exception as exc:
                logger.exception(
                    "admin_task.audit_export.failed",
                    extra={"task_id": str(task_id), "actor_sub": actor_sub},
                )
                await session.rollback()
                await self._mark_failed_isolated(task_id, str(exc))

    # -----------------------------------------------------------------
    # Eval-runs

    def spawn_eval_run(
        self,
        task_id: UUID,
        providers: list[str],
        pairs: list[Any],
        actor_sub: str,
    ) -> asyncio.Task[None]:
        return asyncio.create_task(
            self._run_eval(task_id, providers, pairs, actor_sub),
            name=f"admin_task_eval_run_{task_id}",
        )

    async def _run_eval(
        self,
        task_id: UUID,
        providers: list[str],
        pairs: list[Any],
        actor_sub: str,
    ) -> None:
        # Lazy import to avoid циклов.
        from src.api.admin.eval_runs_schemas import EvalRunProviderResult
        from src.api.admin.eval_runs_service import _aggregate_judge_metrics
        from src.eval.judge import MockJudge
        from src.eval.report import aggregate_results
        from src.eval.runner import run_dataset

        async with self._session_factory() as session:
            task_repo = AdminTaskRepository(session)
            try:
                await task_repo.mark_running(task_id)
                results: list[EvalRunProviderResult] = []
                for provider_name in providers:
                    provider = MockProvider()
                    judge = MockJudge()
                    pair_results = await run_dataset(
                        pairs,
                        provider,
                        provider_name=provider_name,
                        judge=judge,
                    )
                    agg = aggregate_results(pair_results)
                    judge_metrics = _aggregate_judge_metrics(pair_results)
                    results.append(
                        EvalRunProviderResult(
                            provider=provider_name,
                            composite_score=agg.composite_avg,
                            answer_correctness=judge_metrics["answer_correctness"],
                            faithfulness=judge_metrics["faithfulness"],
                            citation_accuracy=agg.citation_accuracy_avg,
                            refusal_correctness=judge_metrics["refusal_correctness"],
                            avg_latency_ms=int(agg.latency_p50 * 1000),
                            cost_per_query_rub=agg.cost_per_query_avg,
                        )
                    )

                row = await task_repo.get(task_id)
                if row is not None:
                    row.params = {
                        **row.params,
                        "results": [r.model_dump() for r in results],
                    }
                await task_repo.mark_completed(task_id)
                await session.commit()
            except Exception as exc:
                logger.exception(
                    "admin_task.eval_run.failed",
                    extra={"task_id": str(task_id), "actor_sub": actor_sub},
                )
                await session.rollback()
                await self._mark_failed_isolated(task_id, str(exc))

    # -----------------------------------------------------------------

    async def _mark_failed_isolated(self, task_id: UUID, error: str) -> None:
        """Open fresh session чтобы изолировать failure marking от main
        session rollback. Best-effort: if even this fails, only log."""
        try:
            async with self._session_factory() as session:
                repo = AdminTaskRepository(session)
                await repo.mark_failed(task_id, error=error[:1000])
                await session.commit()
        except Exception:
            logger.exception(
                "admin_task.mark_failed.also_failed",
                extra={"task_id": str(task_id)},
            )


def _build_indexer(session: AsyncSession) -> IndexerService:
    """Build IndexerService с mock provider (MVP без real embeddings worker)."""
    from src.api.search.embeddings import MockEmbeddingProvider

    return IndexerService(EmbeddingRepository(session), MockEmbeddingProvider())


# Module-level singleton — initialized в lifespan, retrieved через dep.
_RUNNER: AdminTaskRunner | None = None


def init_runner(
    session_factory: async_sessionmaker[Any],
    settings: Settings,
) -> AdminTaskRunner:
    """Called in main.py lifespan. Idempotent: subsequent calls replace."""
    global _RUNNER
    _RUNNER = AdminTaskRunner(session_factory=session_factory, settings=settings)
    return _RUNNER


def get_admin_task_runner() -> AdminTaskRunner:
    """FastAPI Depends — overridable в тестах."""
    if _RUNNER is None:
        raise RuntimeError(
            "AdminTaskRunner not initialized — init_runner() must be " "called в FastAPI lifespan."
        )
    return _RUNNER


__all__ = ["AdminTaskRunner", "get_admin_task_runner", "init_runner"]

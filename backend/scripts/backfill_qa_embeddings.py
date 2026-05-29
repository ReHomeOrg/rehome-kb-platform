"""Backfill embeddings для существующих ANSWERED article_questions.

Запускается one-shot после migration 0033 — индексирует все уже-
существующие ANSWERED вопросы (которые до этого не попадали в RAG
corpus). Idempotent: ON CONFLICT DO UPDATE в QAEmbeddingRepository.upsert
делает повторный запуск no-op'ом по существующим rows.

Usage:
    python -m scripts.backfill_qa_embeddings              # mock provider (default)
    EMBEDDING_PROVIDER=hf python -m scripts.backfill_qa_embeddings  # production

Exit code:
    0 — все ANSWERED indexed (включая 0 строк — empty corpus).
    1 — provider / DB error mid-iteration.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import ArticleQuestion
from src.api.articles.questions_repository import ArticleQuestionRepository
from src.api.config import get_settings
from src.api.db import get_engine
from src.api.search.qa_indexer import QuestionIndexer
from src.api.search.repository import QAEmbeddingRepository
from src.api.search.retrieval import _build_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> int:
    settings = get_settings()
    provider = _build_provider(settings)
    engine = get_engine()
    indexed = 0
    failed = 0

    async with AsyncSession(engine, expire_on_commit=False) as session:
        question_repo = ArticleQuestionRepository(session)
        qa_repo = QAEmbeddingRepository(session)
        indexer = QuestionIndexer(qa_repo, question_repo, provider)

        # Iterate всех ANSWERED. На текущем масштабе (десятки questions)
        # одного transaction достаточно; при больших volumes — batching
        # backlog (worker pattern, не one-shot script).
        stmt = select(ArticleQuestion.id).where(ArticleQuestion.status == "ANSWERED")
        result = await session.execute(stmt)
        question_ids = [row[0] for row in result.all()]

        logger.info("backfill_qa.start", extra={"answered_total": len(question_ids)})

        for qid in question_ids:
            ok = await indexer.index_question(qid)
            if ok:
                indexed += 1
            else:
                failed += 1
            await session.commit()

    logger.info(
        "backfill_qa.done",
        extra={"indexed": indexed, "failed": failed, "total": len(question_ids)},
    )
    print(f"\n=== Summary: indexed={indexed}, failed={failed}, total={len(question_ids)} ===")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

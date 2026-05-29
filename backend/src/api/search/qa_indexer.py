"""QuestionIndexer — Q&A → embeddings (2026-05-29, ТЗ Чат-поиск §«корпуса»).

Sibling of `IndexerService`, ориентированный на article_questions:
1. Fetch question row; skip если status≠ANSWERED (defence-in-depth —
   call-site не должен dispatch'ить для non-ANSWERED, но мы guard'имся
   на случай race / direct invocation).
2. Mask PII в (question.body + answer_body) — user-supplied text может
   содержать phone/email; даже после ANSWERED не хотим leak'нуть в
   retrieval result / LLM context.
3. Embed combined text единственным vector'ом (короткий текст, chunking
   не нужен).
4. Upsert через QAEmbeddingRepository (ON CONFLICT replay-safe).

`mark_dismissed` / revert PENDING → `remove_question(id)` — отдельный
method, evict'ит embedding из corpus (терминал-state «нет публичного
ответа»).

Errors swallowed (like IndexerService): question state уже committed
выше по стеку, indexing failure не должна fail'ить moderation request.
Production worker имеет retry policy через outbox event handler.

NB ADR-0003: write-side НЕ enforce'ит access_level. Retrieval JOIN'ит
parent article на каждой query.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Depends

from src.api.articles.questions_repository import (
    ArticleQuestionRepository,
    get_article_question_repository,
)
from src.api.chat.pii_masking import mask_pii
from src.api.config import Settings, get_settings
from src.api.search.embeddings import EmbeddingProvider
from src.api.search.repository import (
    QAEmbeddingRepository,
    get_qa_embedding_repository,
)

logger = logging.getLogger(__name__)


def _compose_indexed_text(question_body: str, answer_body: str) -> str:
    """Combine question + answer для embedding/retrieval.

    Структура matches'ит как пользователь видит Q&A на article page —
    LLM при retrieval получает same shape ('Вопрос: ...\\nОтвет: ...'),
    нечего галлюцинировать.

    PII masking applied на combined text — single pass дешевле и idempotent
    (см. pii_masking.py).
    """
    composed = f"Вопрос: {question_body}\n\nОтвет: {answer_body}"
    return mask_pii(composed).text


class QuestionIndexer:
    """Async indexer for article_question embeddings."""

    def __init__(
        self,
        qa_repo: QAEmbeddingRepository,
        question_repo: ArticleQuestionRepository,
        provider: EmbeddingProvider,
    ) -> None:
        self._qa_repo = qa_repo
        self._question_repo = question_repo
        self._provider = provider

    async def index_question(self, question_id: UUID) -> bool:
        """Fetch question, mask PII, embed, upsert. Returns True если indexed.

        Skip (return False) если:
        - Question не найден (deleted между dispatch и handler).
        - status≠ANSWERED — corpus содержит только ANSWERED (PENDING /
          DISMISSED не visible публично).
        - answer_body пустой — invalid state, но CHECK constraint
          предотвращает (ANSWERED+NULL запрещён); guard для defensive.
        """
        question = await self._question_repo.get_by_id(question_id)
        if question is None:
            logger.info(
                "qa_indexer.skip_not_found",
                extra={"question_id": str(question_id)},
            )
            return False
        if question.status != "ANSWERED":
            logger.info(
                "qa_indexer.skip_non_answered",
                extra={
                    "question_id": str(question_id),
                    "status": question.status,
                },
            )
            return False
        if not question.answer_body:
            # CHECK constraint должен предотвратить, но defence-in-depth:
            # corrupt row → log + skip.
            logger.warning(
                "qa_indexer.skip_empty_answer",
                extra={"question_id": str(question_id)},
            )
            return False

        text = _compose_indexed_text(question.body, question.answer_body)
        try:
            embeddings = await self._provider.embed([text])
        except Exception:
            logger.exception(
                "qa_indexer.embed_failed",
                extra={
                    "question_id": str(question_id),
                    "model_id": self._provider.model_id,
                },
            )
            return False

        try:
            await self._qa_repo.upsert(
                question_id=question_id,
                embedding=embeddings[0],
                text_indexed=text,
                model_id=self._provider.model_id,
            )
            logger.info(
                "qa_indexer.indexed",
                extra={
                    "question_id": str(question_id),
                    "model_id": self._provider.model_id,
                },
            )
            return True
        except Exception:
            logger.exception(
                "qa_indexer.upsert_failed",
                extra={"question_id": str(question_id)},
            )
            return False

    async def remove_question(self, question_id: UUID) -> int:
        """Evict embeddings одного question'а (любой model_id).

        Вызывается на DISMISSED / revert PENDING — public users не должны
        больше получать этот ответ через chat retrieval.
        """
        try:
            n = await self._qa_repo.delete_by_question(question_id)
            logger.info(
                "qa_indexer.removed",
                extra={"question_id": str(question_id), "deleted": n},
            )
            return n
        except Exception:
            logger.exception(
                "qa_indexer.remove_failed",
                extra={"question_id": str(question_id)},
            )
            return 0


def get_question_indexer(
    qa_repo: QAEmbeddingRepository = Depends(get_qa_embedding_repository),
    question_repo: ArticleQuestionRepository = Depends(get_article_question_repository),
    settings: Settings = Depends(get_settings),
) -> QuestionIndexer:
    """FastAPI dependency — QuestionIndexer с settings-driven provider.

    Использует тот же provider что и article indexer (см.
    `IndexerService` для аналогичной dependency wiring) — model_id
    consistency обязательна, иначе retrieval с другим model_id вернёт
    пустоту по Q&A corpus'у.
    """
    # Lazy import — avoid retrieval ↔ qa_indexer circular.
    from src.api.search.retrieval import _build_provider

    return QuestionIndexer(qa_repo, question_repo, _build_provider(settings))

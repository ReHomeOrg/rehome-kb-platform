"""Article Q&A repository (ТЗ §2, 2026-05-28)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import ArticleQuestion
from src.api.db import get_session

ArticleQuestionStatus = Literal["PENDING", "ANSWERED", "DISMISSED"]


class ArticleQuestionRepository:
    """Storage layer для article_questions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        article_id: UUID,
        author_sub: str,
        body: str,
    ) -> ArticleQuestion:
        """INSERT new question со status=PENDING.

        Caller отвечает за `session.commit()` (ADR-0026 atomic pattern).
        """
        row = ArticleQuestion(
            article_id=article_id,
            author_sub=author_sub,
            body=body,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_by_id(self, question_id: UUID) -> ArticleQuestion | None:
        stmt = select(ArticleQuestion).where(ArticleQuestion.id == question_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_public_for_article(
        self,
        article_id: UUID,
        *,
        limit: int = 50,
    ) -> list[ArticleQuestion]:
        """Public view — только ANSWERED, newest first.

        Used для article detail page Q&A section. Frontend сортирует
        DESC by answered_at — newest answers сверху.
        """
        stmt = (
            select(ArticleQuestion)
            .where(
                ArticleQuestion.article_id == article_id,
                ArticleQuestion.status == "ANSWERED",
            )
            .order_by(ArticleQuestion.answered_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_admin(
        self,
        *,
        status_filter: ArticleQuestionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ArticleQuestion], int]:
        """Admin moderation queue. Returns (rows, total_count)."""
        base = select(ArticleQuestion)
        if status_filter is not None:
            base = base.where(ArticleQuestion.status == status_filter)
        rows_stmt = base.order_by(ArticleQuestion.created_at.desc()).limit(limit).offset(offset)
        count_stmt = select(func.count()).select_from(base.subquery())

        rows_result = await self._session.execute(rows_stmt)
        rows = list(rows_result.scalars().all())
        total = (await self._session.execute(count_stmt)).scalar_one()
        return rows, int(total)

    async def mark_answered(
        self,
        question_id: UUID,
        *,
        answer_body: str,
        answerer_sub: str,
    ) -> ArticleQuestion | None:
        """PENDING / DISMISSED → ANSWERED. Returns updated row или None.

        При revert из DISMISSED — `dismiss_reason` clear'ится: иначе
        admin view показывает stale «причину отклонения» для теперь-
        опубликованного ответа (misleading audit trail).
        """
        row = await self.get_by_id(question_id)
        if row is None:
            return None
        now = datetime.now(UTC)
        row.status = "ANSWERED"
        row.answer_body = answer_body
        row.answerer_sub = answerer_sub
        row.answered_at = now
        row.updated_at = now
        # Clear stale dismiss_reason (was set если revert DISMISSED→ANSWERED).
        row.dismiss_reason = None
        await self._session.flush()
        return row

    async def mark_dismissed(
        self,
        question_id: UUID,
        *,
        reason: str | None,
    ) -> ArticleQuestion | None:
        """PENDING → DISMISSED. Returns updated row или None.

        ANSWERED → DISMISSED НЕ allowed (через router 409): public users
        already saw answer; unpublish'ить нельзя retroactively без
        article-level archive. Use case: ошибочно опубликовали — fix
        via article archive, не dismiss.
        """
        row = await self.get_by_id(question_id)
        if row is None:
            return None
        if row.status == "ANSWERED":
            # Caller (router) обрабатывает 409.
            return row
        now = datetime.now(UTC)
        # Clear answer_body — был None в PENDING, остаётся None.
        row.status = "DISMISSED"
        row.dismiss_reason = reason
        row.answer_body = None
        row.answerer_sub = None
        row.answered_at = None
        row.updated_at = now
        await self._session.flush()
        return row

    async def count_by_article(
        self,
        *,
        limit: int = 50,
    ) -> list[tuple[UUID, str, str, int, int, int]]:
        """Per-article Q&A counts для admin analytics dashboard.

        Returns `[(article_id, slug, title, pending, answered, dismissed), ...]`
        sorted by `pending DESC` (content gap signal — статьи с большим
        backlog'ом нуждаются в moderation attention) then `total DESC`.

        Articles без вопросов НЕ в result (LEFT JOIN'ом нет смысла —
        список нулей не полезен).
        """
        from sqlalchemy import case

        from src.api.articles.models import Article

        # COUNT(CASE WHEN status='X' THEN 1 END) — counts только matching rows.
        pending_col = func.count(case((ArticleQuestion.status == "PENDING", 1))).label("pending")
        answered_col = func.count(case((ArticleQuestion.status == "ANSWERED", 1))).label("answered")
        dismissed_col = func.count(case((ArticleQuestion.status == "DISMISSED", 1))).label(
            "dismissed"
        )
        total_col = func.count().label("total")

        stmt = (
            select(
                ArticleQuestion.article_id,
                Article.slug,
                Article.title,
                pending_col,
                answered_col,
                dismissed_col,
                total_col,
            )
            .join(Article, Article.id == ArticleQuestion.article_id)
            .group_by(ArticleQuestion.article_id, Article.slug, Article.title)
            .order_by(pending_col.desc(), total_col.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            (
                row.article_id,
                row.slug,
                row.title,
                int(row.pending),
                int(row.answered),
                int(row.dismissed),
            )
            for row in result.all()
        ]


def get_article_question_repository(
    session: AsyncSession = Depends(get_session),
) -> ArticleQuestionRepository:
    return ArticleQuestionRepository(session)


__all__ = ["ArticleQuestionRepository", "get_article_question_repository"]

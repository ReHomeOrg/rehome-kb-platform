"""Integration: DB-level CHECK constraint `ck_article_questions_answered_consistency`.

Reviewer 2026-05-28 backlog #4 / finding #343.3: constraint покрыт только
косвенно через router-level Pydantic guards + repository state transitions.
Defence-in-depth: если кто-то обходит router (raw SQL, direct ORM call,
поломанный repo refactor), DB должна последней отказать невалидное
состояние.

Constraint (см. `alembic/versions/20260528_010000_article_questions.py`):

    (status = 'ANSWERED'
        AND answer_body IS NOT NULL
        AND answerer_sub IS NOT NULL
        AND answered_at IS NOT NULL)
    OR
    (status != 'ANSWERED'
        AND answer_body IS NULL
        AND answerer_sub IS NULL
        AND answered_at IS NULL)

Эти тесты делают raw asyncpg INSERT'ы (bypass'ат SQLAlchemy ORM /
Pydantic) и ожидают `CheckViolationError`. Тесты cleanup'ят за собой
через DELETE (FK CASCADE'нет если article archived).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest

RAW_DSN = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb"
).replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def article_id() -> AsyncIterator[UUID]:
    """Insert a temp article + cleanup. Article_id для FK reference в
    тестах CHECK constraint'а."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        article_id_raw = await conn.fetchval(
            """
            INSERT INTO articles (
                slug, title, body_markdown, audience, language, category,
                tags, access_level, status
            ) VALUES (
                $1, 'Test Article', 'body', 'all', 'ru', 'test',
                '[]'::jsonb, 'PUBLIC', 'PUBLISHED'
            ) RETURNING id
            """,
            f"check-constraint-test-{uuid4().hex[:8]}",
        )
        assert article_id_raw is not None
        article_uuid = UUID(str(article_id_raw))
        yield article_uuid
    finally:
        # Article CASCADE удаляет связанные article_questions автоматически.
        await conn.execute("DELETE FROM articles WHERE id = $1", article_uuid)
        await conn.close()


# ---------------------------------------------------------------------------
# Negative tests — CHECK должен отвергать невалидные состояния


@pytest.mark.integration
async def test_check_pending_with_answer_body_violates(article_id: UUID) -> None:
    """PENDING + answer_body != NULL → CheckViolationError.

    PENDING значит «ещё нет ответа»; иметь answer_body запрещено
    constraint'ом (это inconsistent state).
    """
    conn = await asyncpg.connect(RAW_DSN)
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO article_questions (
                    article_id, author_sub, body, status, answer_body
                ) VALUES ($1, $2, $3, 'PENDING', 'unauthorized answer')
                """,
                article_id,
                "user-sub",
                "question body",
            )
    finally:
        await conn.close()


@pytest.mark.integration
async def test_check_answered_without_answer_body_violates(article_id: UUID) -> None:
    """ANSWERED + answer_body IS NULL → CheckViolationError.

    ANSWERED обязан иметь answer_body (всё-или-ничего invariant).
    """
    conn = await asyncpg.connect(RAW_DSN)
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO article_questions (
                    article_id, author_sub, body, status,
                    answer_body, answerer_sub, answered_at
                ) VALUES ($1, $2, $3, 'ANSWERED', NULL, 'staff', NOW())
                """,
                article_id,
                "user-sub",
                "question",
            )
    finally:
        await conn.close()


@pytest.mark.integration
async def test_check_answered_without_answerer_sub_violates(article_id: UUID) -> None:
    """ANSWERED + answerer_sub IS NULL → CheckViolationError."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO article_questions (
                    article_id, author_sub, body, status,
                    answer_body, answerer_sub, answered_at
                ) VALUES ($1, $2, $3, 'ANSWERED', 'answer body', NULL, NOW())
                """,
                article_id,
                "user-sub",
                "question",
            )
    finally:
        await conn.close()


@pytest.mark.integration
async def test_check_answered_without_answered_at_violates(article_id: UUID) -> None:
    """ANSWERED + answered_at IS NULL → CheckViolationError."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO article_questions (
                    article_id, author_sub, body, status,
                    answer_body, answerer_sub, answered_at
                ) VALUES ($1, $2, $3, 'ANSWERED', 'answer body', 'staff', NULL)
                """,
                article_id,
                "user-sub",
                "question",
            )
    finally:
        await conn.close()


@pytest.mark.integration
async def test_check_dismissed_with_answer_body_violates(article_id: UUID) -> None:
    """DISMISSED + answer_body != NULL → CheckViolationError.

    DISMISSED — terminal state «нет публичного ответа»; answer_body
    запрещён (предотвращает leak предыдущего ответа после revert
    через прямой UPDATE).
    """
    conn = await asyncpg.connect(RAW_DSN)
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO article_questions (
                    article_id, author_sub, body, status, answer_body
                ) VALUES ($1, $2, $3, 'DISMISSED', 'stale answer')
                """,
                article_id,
                "user-sub",
                "question",
            )
    finally:
        await conn.close()


@pytest.mark.integration
async def test_check_invalid_status_value_violates(article_id: UUID) -> None:
    """Status NOT IN ('PENDING','ANSWERED','DISMISSED') → CheckViolationError
    (separate ck_article_questions_status constraint)."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO article_questions (
                    article_id, author_sub, body, status
                ) VALUES ($1, $2, $3, 'INVALID_STATUS')
                """,
                article_id,
                "user-sub",
                "question",
            )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Positive tests — valid states accepted


@pytest.mark.integration
async def test_pending_with_nulls_accepted(article_id: UUID) -> None:
    """PENDING + all answer fields NULL → OK (canonical PENDING state)."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        question_id = await conn.fetchval(
            """
            INSERT INTO article_questions (
                article_id, author_sub, body, status
            ) VALUES ($1, $2, $3, 'PENDING')
            RETURNING id
            """,
            article_id,
            "user-sub",
            "valid pending question",
        )
        assert question_id is not None
    finally:
        await conn.close()


@pytest.mark.integration
async def test_answered_with_all_fields_accepted(article_id: UUID) -> None:
    """ANSWERED + answer_body + answerer_sub + answered_at — все NOT NULL → OK."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        question_id = await conn.fetchval(
            """
            INSERT INTO article_questions (
                article_id, author_sub, body, status,
                answer_body, answerer_sub, answered_at
            ) VALUES ($1, $2, $3, 'ANSWERED', 'real answer', 'staff', NOW())
            RETURNING id
            """,
            article_id,
            "user-sub",
            "valid answered question",
        )
        assert question_id is not None
    finally:
        await conn.close()


@pytest.mark.integration
async def test_dismissed_with_dismiss_reason_accepted(article_id: UUID) -> None:
    """DISMISSED + dismiss_reason set + answer fields NULL → OK."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        question_id = await conn.fetchval(
            """
            INSERT INTO article_questions (
                article_id, author_sub, body, status, dismiss_reason
            ) VALUES ($1, $2, $3, 'DISMISSED', 'off-topic')
            RETURNING id
            """,
            article_id,
            "user-sub",
            "valid dismissed question",
        )
        assert question_id is not None
    finally:
        await conn.close()

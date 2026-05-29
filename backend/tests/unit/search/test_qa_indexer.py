"""Unit tests for QuestionIndexer (2026-05-29, Q&A → RAG)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.search.qa_indexer import QuestionIndexer, _compose_indexed_text


def _make_indexer(
    question: object | None = None,
    embed_raises: Exception | None = None,
    upsert_raises: Exception | None = None,
    delete_returns: int = 1,
    delete_raises: Exception | None = None,
) -> tuple[QuestionIndexer, MagicMock, MagicMock, MagicMock]:
    qa_repo = MagicMock()
    qa_repo.upsert = AsyncMock(side_effect=upsert_raises)
    qa_repo.delete_by_question = AsyncMock(side_effect=delete_raises, return_value=delete_returns)

    question_repo = MagicMock()
    question_repo.get_by_id = AsyncMock(return_value=question)

    provider = MagicMock()
    provider.model_id = "mock-test-v1"
    if embed_raises is not None:
        provider.embed = AsyncMock(side_effect=embed_raises)
    else:
        provider.embed = AsyncMock(return_value=[[0.1] * 4])

    return QuestionIndexer(qa_repo, question_repo, provider), qa_repo, question_repo, provider


def _answered(
    *,
    body: str = "Как продлить аренду?",
    answer: str | None = "Через личный кабинет — раздел «Договоры».",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status="ANSWERED",
        body=body,
        answer_body=answer,
        article_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# _compose_indexed_text


def test_compose_combines_question_and_answer() -> None:
    text = _compose_indexed_text("Q?", "A!")
    assert "Q?" in text
    assert "A!" in text
    assert text.index("Q?") < text.index("A!")  # ordering preserved


def test_compose_masks_pii_in_question() -> None:
    """ФЗ-152: user question body может содержать phone/email; mask
    перед сохранением в индексе."""
    text = _compose_indexed_text(
        "Мой email user@example.com — как уведомлять?",
        "Через личный кабинет.",
    )
    assert "user@example.com" not in text
    assert "[EMAIL]" in text


def test_compose_masks_pii_in_answer() -> None:
    """Defensive: staff может accidentally paste user contact в answer."""
    text = _compose_indexed_text(
        "Как связаться с менеджером?",
        "Менеджер — +7 916 123-45-67.",
    )
    assert "+7 916" not in text
    assert "[PHONE]" in text


# ---------------------------------------------------------------------------
# index_question


@pytest.mark.asyncio
async def test_index_question_indexes_answered() -> None:
    q = _answered()
    indexer, qa_repo, question_repo, provider = _make_indexer(question=q)
    ok = await indexer.index_question(q.id)
    assert ok is True
    question_repo.get_by_id.assert_awaited_once_with(q.id)
    provider.embed.assert_awaited_once()
    qa_repo.upsert.assert_awaited_once()
    call = qa_repo.upsert.await_args
    assert call.kwargs["question_id"] == q.id
    assert call.kwargs["model_id"] == "mock-test-v1"
    # text_indexed материализован — содержит question + answer.
    assert "Как продлить аренду?" in call.kwargs["text_indexed"]
    assert "Через личный кабинет" in call.kwargs["text_indexed"]
    # embedding передан в upsert.
    assert isinstance(call.kwargs["embedding"], list)


@pytest.mark.asyncio
async def test_index_question_skips_not_found() -> None:
    indexer, qa_repo, _question_repo, provider = _make_indexer(question=None)
    ok = await indexer.index_question(uuid4())
    assert ok is False
    provider.embed.assert_not_called()
    qa_repo.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_index_question_skips_pending() -> None:
    q = SimpleNamespace(id=uuid4(), status="PENDING", body="q", answer_body=None)
    indexer, qa_repo, _question_repo, provider = _make_indexer(question=q)
    ok = await indexer.index_question(q.id)
    assert ok is False
    provider.embed.assert_not_called()
    qa_repo.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_index_question_skips_dismissed() -> None:
    q = SimpleNamespace(id=uuid4(), status="DISMISSED", body="q", answer_body=None)
    indexer, qa_repo, _question_repo, _provider = _make_indexer(question=q)
    ok = await indexer.index_question(q.id)
    assert ok is False
    qa_repo.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_index_question_skips_empty_answer() -> None:
    """ANSWERED + empty answer_body → CHECK constraint должен предотвращать;
    defensive guard в indexer."""
    q = SimpleNamespace(id=uuid4(), status="ANSWERED", body="q", answer_body="")
    indexer, qa_repo, _question_repo, _provider = _make_indexer(question=q)
    ok = await indexer.index_question(q.id)
    assert ok is False
    qa_repo.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_index_question_swallows_embed_failure() -> None:
    q = _answered()
    indexer, qa_repo, _question_repo, _provider = _make_indexer(
        question=q, embed_raises=RuntimeError("provider down")
    )
    ok = await indexer.index_question(q.id)
    assert ok is False
    qa_repo.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_index_question_swallows_upsert_failure() -> None:
    q = _answered()
    indexer, qa_repo, _question_repo, _provider = _make_indexer(
        question=q, upsert_raises=RuntimeError("db gone")
    )
    ok = await indexer.index_question(q.id)
    assert ok is False
    qa_repo.upsert.assert_awaited_once()  # attempted


@pytest.mark.asyncio
async def test_index_question_idempotent() -> None:
    """Repeat indexing same answered question — upsert вызывается дважды,
    same args (ON CONFLICT DO UPDATE — replay-safe)."""
    q = _answered()
    indexer, qa_repo, _question_repo, _provider = _make_indexer(question=q)
    await indexer.index_question(q.id)
    await indexer.index_question(q.id)
    assert qa_repo.upsert.await_count == 2
    first = qa_repo.upsert.await_args_list[0].kwargs
    second = qa_repo.upsert.await_args_list[1].kwargs
    assert first["text_indexed"] == second["text_indexed"]
    assert first["embedding"] == second["embedding"]


@pytest.mark.asyncio
async def test_index_question_pii_persisted_masked() -> None:
    """User-supplied body с phone — `text_indexed` (что persisted)
    содержит [PHONE], не raw number."""
    q = _answered(
        body="Контакт менеджера? +7 916 123-45-67",
        answer="Менеджер ответит в чате.",
    )
    indexer, qa_repo, _question_repo, _provider = _make_indexer(question=q)
    await indexer.index_question(q.id)
    persisted = qa_repo.upsert.await_args.kwargs["text_indexed"]
    assert "+7 916" not in persisted
    assert "[PHONE]" in persisted


# ---------------------------------------------------------------------------
# remove_question


@pytest.mark.asyncio
async def test_remove_question_deletes_all_models() -> None:
    indexer, qa_repo, _question_repo, _provider = _make_indexer(delete_returns=2)
    n = await indexer.remove_question(uuid4())
    assert n == 2
    qa_repo.delete_by_question.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_question_swallows_failure() -> None:
    indexer, qa_repo, _question_repo, _provider = _make_indexer(
        delete_raises=RuntimeError("db gone")
    )
    n = await indexer.remove_question(uuid4())
    assert n == 0
    qa_repo.delete_by_question.assert_awaited_once()

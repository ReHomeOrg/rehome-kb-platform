"""Unit tests for `_maybe_capture_no_answer` (2026-05-29).

Тестируется pure-function gating + repo.record call'ы. End-to-end через
chat router — отдельный test (covered as integration smoke в test_router*).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.chat.router import _maybe_capture_no_answer
from src.api.search.repository import RetrievalHit


def _hit() -> RetrievalHit:
    return RetrievalHit(
        article_id=uuid4(),
        slug="x",
        title="X",
        chunk_index=0,
        text="t",
        char_start=0,
        char_end=1,
        score=0.1,
    )


def _make_repo() -> MagicMock:
    repo = MagicMock()
    repo.record = AsyncMock()
    return repo


@pytest.mark.asyncio
async def test_capture_writes_when_rag_enabled_and_no_hits() -> None:
    repo = _make_repo()
    sid = uuid4()
    await _maybe_capture_no_answer(
        repo,
        capture_enabled=True,
        rag_enabled=True,
        retrieved_chunks=[],
        query="как продлить договор",
        author_sub="user-1",
        session_id=sid,
    )
    repo.record.assert_awaited_once()
    kwargs = repo.record.await_args.kwargs
    assert kwargs["query"] == "как продлить договор"
    assert kwargs["author_sub"] == "user-1"
    assert kwargs["chat_session_id"] == sid


@pytest.mark.asyncio
async def test_capture_skips_when_chunks_present() -> None:
    """RAG нашёл что-то → query был успешно отвечен, capture не нужен."""
    repo = _make_repo()
    await _maybe_capture_no_answer(
        repo,
        capture_enabled=True,
        rag_enabled=True,
        retrieved_chunks=[_hit()],
        query="q",
        author_sub="u",
        session_id=uuid4(),
    )
    repo.record.assert_not_called()


@pytest.mark.asyncio
async def test_capture_skips_when_rag_disabled() -> None:
    """RAG off → nothing meaningful happened; capture не имеет смысла."""
    repo = _make_repo()
    await _maybe_capture_no_answer(
        repo,
        capture_enabled=True,
        rag_enabled=False,
        retrieved_chunks=[],
        query="q",
        author_sub="u",
        session_id=uuid4(),
    )
    repo.record.assert_not_called()


@pytest.mark.asyncio
async def test_capture_skips_when_feature_flag_off() -> None:
    """`CHAT_CAPTURE_UNANSWERED_ENABLED=False` — bypass."""
    repo = _make_repo()
    await _maybe_capture_no_answer(
        repo,
        capture_enabled=False,
        rag_enabled=True,
        retrieved_chunks=[],
        query="q",
        author_sub="u",
        session_id=uuid4(),
    )
    repo.record.assert_not_called()


@pytest.mark.asyncio
async def test_capture_swallows_repo_failure() -> None:
    """Chat не должен fail'ить на capture side-effect (defensive)."""
    repo = _make_repo()
    repo.record = AsyncMock(side_effect=RuntimeError("db gone"))
    # Should not raise.
    await _maybe_capture_no_answer(
        repo,
        capture_enabled=True,
        rag_enabled=True,
        retrieved_chunks=[],
        query="q",
        author_sub="u",
        session_id=uuid4(),
    )
    repo.record.assert_awaited_once()

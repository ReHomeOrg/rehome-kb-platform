"""Unit tests для chat RAG integration (#136)."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.llm import LLMResponse, MockProvider, get_llm_provider
from src.api.chat.models import ChatMessage, ChatSession
from src.api.chat.repository import ChatRepository, get_chat_repository
from src.api.chat.system_prompt import (
    NO_CONTEXT_DIRECTIVE,
    SYSTEM_PROMPT,
    build_rag_system_prompt,
    hits_to_citations,
)
from src.api.main import app
from src.api.search.repository import RetrievalHit
from src.api.search.retrieval import RetrievalService, get_retrieval_service


def _make_session() -> ChatSession:
    s = ChatSession()
    s.id = uuid4()
    s.user_id = uuid4()
    s.session_token = uuid4()
    s.scope = "tenant"
    s.context = {}
    s.created_at = datetime.now(UTC)
    s.expires_at = datetime.now(UTC) + timedelta(days=1)
    s.deleted_at = None
    return s


def _make_message(session_id: object, role: str, content: str) -> ChatMessage:
    m = ChatMessage()
    m.id = uuid4()
    m.session_id = session_id  # type: ignore[assignment]
    m.role = role
    m.content = content
    m.citations = []
    m.feedback = None
    m.token_count = None
    m.duration_ms = None
    m.created_at = datetime.now(UTC)
    return m


def _hit(
    article_id: UUID | None = None,
    title: str = "Сервисный платёж",
    slug: str = "service-fee",
    chunk_index: int = 0,
    text: str = "Сервисный платёж — невозвратный...",
    score: float = 0.025,
) -> RetrievalHit:
    return RetrievalHit(
        article_id=article_id or uuid4(),
        slug=slug,
        title=title,
        chunk_index=chunk_index,
        text=text,
        char_start=0,
        char_end=len(text),
        score=score,
    )


# ---------------------------------------------------------------------------
# build_rag_system_prompt pure-function unit tests


def test_build_rag_prompt_empty_chunks_returns_base() -> None:
    """Empty chunks → unchanged SYSTEM_PROMPT (idempotent)."""
    assert build_rag_system_prompt([]) == SYSTEM_PROMPT


def test_build_rag_prompt_includes_chunks() -> None:
    """Non-empty chunks → base + numbered context block."""
    prompt = build_rag_system_prompt(
        [
            _hit(title="Аренда", text="Договор аренды..."),
            _hit(title="Залог", text="Залога нет..."),
        ]
    )
    assert SYSTEM_PROMPT in prompt
    assert "## Контекст из базы знаний" in prompt
    assert "[1]" in prompt
    assert "[2]" in prompt
    assert "Аренда" in prompt
    assert "Договор аренды..." in prompt
    assert "Залог" in prompt


def test_build_rag_prompt_instructs_citation_format() -> None:
    """Augmented prompt просит LLM цитировать `[N]`."""
    prompt = build_rag_system_prompt([_hit()])
    assert "[N]" in prompt or "[1]" in prompt
    assert "выдумывай" in prompt or "не выдумывай" in prompt


# ---------------------------------------------------------------------------
# hits_to_citations


def test_hits_to_citations_empty() -> None:
    assert hits_to_citations([]) == []


def test_hits_to_citations_structure() -> None:
    aid = uuid4()
    hit = _hit(article_id=aid, slug="my-slug", title="My Title", chunk_index=3, score=0.04)
    [c] = hits_to_citations([hit])
    assert c["type"] == "article"
    assert c["id"] == str(aid)
    assert c["title"] == "My Title"
    assert c["slug"] == "my-slug"
    assert c["chunk_index"] == 3
    assert c["score"] == pytest.approx(0.04)
    assert c["url"] == "/articles/my-slug"


def test_hits_to_citations_article_question_variant() -> None:
    """Q&A hit → type='article_question', anchor URL `#question-{id}`,
    question_id field включён (2026-05-29, ТЗ Чат-поиск §«корпуса»)."""
    aid = uuid4()
    qid = uuid4()
    qa_hit = RetrievalHit(
        article_id=aid,
        slug="rent-contract",
        title="Договор аренды",
        chunk_index=0,
        text="Q+A текст",
        char_start=0,
        char_end=9,
        score=0.016,
        source_type="article_question",
        question_id=qid,
    )
    [c] = hits_to_citations([qa_hit])
    assert c["type"] == "article_question"
    assert c["id"] == str(aid)
    assert c["question_id"] == str(qid)
    assert c["url"] == f"/articles/rent-contract#question-{qid}"


# ---------------------------------------------------------------------------
# fixtures для router-уровневых тестов


@pytest.fixture
def get_session_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def record_turn_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def override_repo(
    get_session_mock: AsyncMock,
    record_turn_mock: AsyncMock,
) -> Iterator[tuple[AsyncMock, AsyncMock]]:
    repo = ChatRepository.__new__(ChatRepository)
    repo.get_session_by_owner = get_session_mock  # type: ignore[method-assign]
    repo.list_messages = AsyncMock(return_value=[])  # type: ignore[method-assign]
    repo.record_chat_turn = record_turn_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield get_session_mock, record_turn_mock
    app.dependency_overrides.pop(get_chat_repository, None)


@pytest.fixture
def override_llm() -> Iterator[AsyncMock]:
    complete_mock = AsyncMock(
        return_value=LLMResponse(content="reply", token_count=10, duration_ms=42),
    )
    provider = MockProvider.__new__(MockProvider)
    provider.complete = complete_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_llm_provider] = lambda: provider
    yield complete_mock
    app.dependency_overrides.pop(get_llm_provider, None)


@pytest.fixture
def retrieval_search_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def override_retrieval(retrieval_search_mock: AsyncMock) -> Iterator[AsyncMock]:
    svc = RetrievalService.__new__(RetrievalService)
    svc.search = retrieval_search_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_retrieval_service] = lambda: svc
    yield retrieval_search_mock
    app.dependency_overrides.pop(get_retrieval_service, None)


# ---------------------------------------------------------------------------
# RAG_ENABLED=False — no-op (regression guard)


def test_rag_disabled_does_not_call_retrieval(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_ENABLED", "false")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "договор"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    override_retrieval.assert_not_awaited()
    # Citations всё ещё [] в DB write.
    assert record_turn_mock.call_args.kwargs["citations"] == []
    # System prompt unchanged.
    sys_prompt = override_llm.call_args.args[1]
    # RAG не augment'ил base prompt; greeting-директива дописывается отдельно.
    assert sys_prompt.startswith(SYSTEM_PROMPT)
    assert "## Контекст из базы знаний" not in sys_prompt


# ---------------------------------------------------------------------------
# RAG_ENABLED=True — happy path


def test_rag_enabled_calls_retrieval_and_augments_prompt(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = [
        _hit(title="Договор аренды", text="Договор...", slug="rent-contract"),
    ]

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "договор"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    retrieval_search_mock.assert_awaited_once()
    # System prompt augmented.
    sys_prompt = override_llm.call_args.args[1]
    assert "## Контекст из базы знаний" in sys_prompt
    assert "Договор аренды" in sys_prompt
    # Citations populated в DB write.
    citations = record_turn_mock.call_args.kwargs["citations"]
    assert len(citations) == 1
    assert citations[0]["title"] == "Договор аренды"
    assert citations[0]["url"] == "/articles/rent-contract"
    # Response body содержит... assistant message (DB-loaded; citations
    # из mock _make_message были []; реальный DB persist'ит из call_args).


def test_rag_enabled_passes_access_levels_to_retrieval(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0003: access_levels из текущего scope (JWT roles)."""
    from src.api.auth.scope import AccessLevel

    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    levels = retrieval_search_mock.call_args.kwargs["access_levels"]
    assert AccessLevel.PUBLIC in levels
    assert AccessLevel.LOGGED in levels  # tenant role даёт LOGGED


def test_rag_enabled_anon_gets_only_public(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anon (нет JWT): access_levels={PUBLIC}."""
    from src.api.auth.scope import AccessLevel

    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    session.user_id = None  # anon session
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")

    # Anon flow — нет Authorization header; chat поддерживает session_token.
    client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "x"},
        headers={"X-Chat-Session-Token": str(session.session_token)},
    )
    levels = retrieval_search_mock.call_args.kwargs["access_levels"]
    assert levels == frozenset({AccessLevel.PUBLIC})


# ---------------------------------------------------------------------------
# defensive: retrieval exception не валит chat


def test_rag_retrieval_exception_degrades_gracefully(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieval бросает → chat работает (degraded mode, no context)."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.side_effect = RuntimeError("pgvector down")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # Citations empty (no retrieval result).
    assert record_turn_mock.call_args.kwargs["citations"] == []
    # System prompt не augmented.
    sys_prompt = override_llm.call_args.args[1]
    # RAG не augment'ил base prompt; greeting-директива дописывается отдельно.
    assert sys_prompt.startswith(SYSTEM_PROMPT)
    assert "## Контекст из базы знаний" not in sys_prompt


def test_rag_enabled_empty_retrieval_unchanged_prompt(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieval вернул [] → system prompt = SYSTEM_PROMPT, citations=[]."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert record_turn_mock.call_args.kwargs["citations"] == []
    empty_sys_prompt = override_llm.call_args.args[1]
    assert empty_sys_prompt.startswith(SYSTEM_PROMPT)
    assert "## Контекст из базы знаний" not in empty_sys_prompt


# ---------------------------------------------------------------------------
# SSE flow with RAG


def _parse_sse_events(text: str) -> list[tuple[str, str]]:
    """Парсит SSE response в (event, data) tuples."""
    events: list[tuple[str, str]] = []
    current_event: str | None = None
    for line in text.split("\n"):
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:") and current_event is not None:
            events.append((current_event, line[len("data:") :].strip()))
            current_event = None
    return events


def test_sse_emits_citations_event_after_message_start(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG_ENABLED+SSE: `citations` event между message-start и chunks."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="r")
    retrieval_search_mock.return_value = [_hit(title="X", slug="x", text="чанк")]

    # Используем MockProvider для streaming (deterministic).
    provider = MockProvider()
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        names = [n for n, _ in events]
        assert names[0] == "message-start"
        assert names[1] == "citations"
        # Citations data contains our hit.
        citations_data = json.loads(next(d for n, d in events if n == "citations"))
        assert "data" in citations_data
        assert len(citations_data["data"]) == 1
        assert citations_data["data"][0]["title"] == "X"
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


# ---------------------------------------------------------------------------
# chat.no_answer webhook (#222, ТЗ §5.1)


@pytest.fixture
def chat_dispatch_mock() -> Iterator[AsyncMock]:
    """Override no-op dispatcher с tracking mock."""
    from unittest.mock import MagicMock

    from src.api.webhooks.dispatcher import (
        WebhookEventDispatcher,
        get_webhook_event_dispatcher,
    )

    dispatch = AsyncMock(return_value=1)
    fake = MagicMock(spec=WebhookEventDispatcher)
    fake.dispatch = dispatch
    app.dependency_overrides[get_webhook_event_dispatcher] = lambda: fake
    yield dispatch
    app.dependency_overrides.pop(get_webhook_event_dispatcher, None)


def test_chat_no_answer_fires_when_rag_returns_empty(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    chat_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG enabled + 0 chunks → fire `chat.no_answer`."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "несуществующая тема"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    chat_dispatch_mock.assert_awaited_once()
    kwargs = chat_dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "chat.no_answer"
    payload = kwargs["payload"]
    assert payload["session_id"] == str(session.id)
    assert payload["query"] == "несуществующая тема"
    assert payload["retrieved_sources"] == []


def test_chat_no_answer_skipped_when_rag_has_hits(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    chat_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG enabled + есть hits → no dispatch."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = [_hit()]

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "договор"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    chat_dispatch_mock.assert_not_awaited()


def test_chat_no_answer_skipped_when_rag_disabled(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    chat_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG disabled → no dispatch (chat не grounding'нулся через KB)."""
    monkeypatch.setenv("RAG_ENABLED", "false")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    chat_dispatch_mock.assert_not_awaited()


def test_chat_no_answer_dispatch_failure_does_not_break_chat(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    chat_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatcher exception swallow'ится — chat response ОК."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []
    chat_dispatch_mock.side_effect = RuntimeError("broker down")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_chat_no_answer_fires_when_retrieval_raises(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    chat_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieval exception → `_retrieve_chunks_for_rag` returns [] →
    no_answer fires (KB не дала контекст, signal'им как gap)."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.side_effect = RuntimeError("pgvector down")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    chat_dispatch_mock.assert_awaited_once()
    assert chat_dispatch_mock.call_args.kwargs["event_type"] == "chat.no_answer"


def test_sse_emits_empty_citations_when_rag_disabled(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`citations` event emit'ится даже при RAG_ENABLED=false (consistent order)."""
    monkeypatch.setenv("RAG_ENABLED", "false")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="r")

    provider = MockProvider()
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        events = _parse_sse_events(resp.text)
        names = [n for n, _ in events]
        assert "citations" in names
        cit_data = json.loads(next(d for n, d in events if n == "citations"))
        assert cit_data == {"data": []}
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


# ---------------------------------------------------------------------------
# Confidence-gated escalation (#382, Tier 2) — router-обвязка no-context директивы


def test_rag_enabled_empty_retrieval_appends_no_context_directive(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG on + пустой retrieval → no-context директива дописана в system prompt."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "вопрос без ответа в базе"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    sys_prompt = override_llm.call_args.args[1]
    assert NO_CONTEXT_DIRECTIVE in sys_prompt


def test_rag_enabled_with_context_omits_no_context_directive(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG on + есть контекст → no-context директива НЕ дописывается."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = [_hit()]

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "сервисный платёж"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    sys_prompt = override_llm.call_args.args[1]
    assert NO_CONTEXT_DIRECTIVE not in sys_prompt


def test_rag_disabled_omits_no_context_directive(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG off → no-context директива не форсится (гейт на rag_enabled)."""
    monkeypatch.setenv("RAG_ENABLED", "false")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "договор"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    sys_prompt = override_llm.call_args.args[1]
    assert NO_CONTEXT_DIRECTIVE not in sys_prompt


# ---------------------------------------------------------------------------
# Operator-footer strip (#388) — гейт на has_context


def test_operator_footer_stripped_when_context(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Есть контекст + LLM дописал приписку об операторе → она срезается в persist."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = [_hit()]  # есть контекст
    override_llm.return_value = LLMResponse(
        content="Залога нет. Пожалуйста, обратитесь в поддержку за помощью.",
        token_count=10,
        duration_ms=42,
    )
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "нужен ли залог"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert record_turn_mock.call_args.kwargs["assistant_content"] == "Залога нет."


def test_operator_footer_kept_when_no_context(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Нет контекста (пустой retrieval) → приписка уместна, НЕ срезается."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []  # нет контекста
    override_llm.return_value = LLMResponse(
        content="В базе нет ответа. Обратитесь в поддержку.",
        token_count=10,
        duration_ms=42,
    )
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "экзотический вопрос"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "поддержку" in record_turn_mock.call_args.kwargs["assistant_content"]


# ---------------------------------------------------------------------------
# C23 — жёсткий retrieval-gate (RAG_HARD_GATE_ENABLED)


def test_hard_gate_off_still_calls_llm_without_context(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default (гейт OFF): нет контекста → LLM ВСЁ РАВНО зовётся (прежнее soft-поведение)."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.delenv("RAG_HARD_GATE_ENABLED", raising=False)
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []  # нет контекста
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "экзотический вопрос"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    override_llm.assert_awaited_once()  # LLM вызван (гейт выключен)


def test_hard_gate_on_no_context_skips_llm_deterministic_reply(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Гейт ON + нет уверенного контекста → LLM НЕ вызывается, детерминированный no-answer."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_HARD_GATE_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []  # нет уверенного контекста
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "экзотический вопрос"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    override_llm.assert_not_awaited()  # SECURITY: LLM НЕ вызван (запрет ответа из параметрики)
    kwargs = record_turn_mock.call_args.kwargs
    assert "передам ваш вопрос специалисту" in kwargs["assistant_content"]
    assert kwargs["citations"] == []  # уверенных источников нет


def test_hard_gate_on_with_context_calls_llm(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Гейт ON + есть контекст → LLM зовётся нормально (гейт не мешает уверенным ответам)."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_HARD_GATE_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = [_hit(title="Договор", text="Договор аренды...")]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "договор"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    override_llm.assert_awaited_once()  # есть контекст → LLM зовётся


def test_hard_gate_on_low_score_skips_llm(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Гейт ON + непустой retrieval, но top-score НИЖЕ порога → LLM НЕ вызывается.

    Самый нетривиальный путь C23: `has_context=False` при НЕпустых chunks
    (`RAG_MIN_CONFIDENCE_SCORE > 0`), а не только на пустом retrieval.
    """
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_HARD_GATE_ENABLED", "true")
    monkeypatch.setenv("RAG_MIN_CONFIDENCE_SCORE", "0.9")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    # Непустой retrieval, но score ниже порога 0.9 → has_usable_context=False.
    retrieval_search_mock.return_value = [_hit(score=0.01)]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "договор"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    override_llm.assert_not_awaited()  # low-score → гейт срабатывает (не только на пустом)
    kwargs = record_turn_mock.call_args.kwargs
    assert "передам ваш вопрос специалисту" in kwargs["assistant_content"]
    assert kwargs["citations"] == []  # below-threshold chunks НЕ показываются источниками


def test_hard_gate_persists_zero_token_and_duration(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Гейт ON: детерминированный no-answer persist'ится с token_count=0/duration_ms=0
    (LLM не звали — ни токенов, ни латентности вызова)."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_HARD_GATE_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "экзотический вопрос"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = record_turn_mock.call_args.kwargs
    assert kwargs["token_count"] == 0
    assert kwargs["duration_ms"] == 0


def test_hard_gate_increments_metric_on_trigger(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    override_retrieval: AsyncMock,
    retrieval_search_mock: AsyncMock,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Срабатывание гейта инкрементит `kb_chat_rag_hard_gate_total` (сигнал content-gap)."""
    from src.api.chat.metrics import RAG_HARD_GATE_TOTAL

    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_HARD_GATE_ENABLED", "true")
    get_session_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")
    retrieval_search_mock.return_value = []
    before = float(RAG_HARD_GATE_TOTAL._value.get())  # type: ignore[attr-defined]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "экзотический вопрос"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    after = float(RAG_HARD_GATE_TOTAL._value.get())  # type: ignore[attr-defined]
    assert after == before + 1.0

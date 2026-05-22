"""FastAPI router для `/api/v1/chat/sessions/*` (E3.2 #63).

3 эндпоинта:
- `POST /chat/sessions` — создать session (auth optional). Anon flow
  возвращает `X-Chat-Session-Token` header.
- `GET /chat/sessions/{id}` — owner-gated detail с messages.
- `DELETE /chat/sessions/{id}` — soft-delete (ФЗ-152 right-to-forget).

POST /messages, SSE, feedback, escalate — E3.3+.
"""

import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from src.api.audit import (
    ACTION_CHAT_ESCALATED,
    RESOURCE_CHAT_SESSION,
    AuditRepository,
    format_anon_actor_sub,
    get_audit_repository,
)
from src.api.auth.dependency import get_current_access_levels, get_current_scope
from src.api.auth.scope import AccessLevel, Scope
from src.api.chat.idempotency import process_chat_idempotency_key
from src.api.chat.llm import LLMMessage, LLMProvider, get_llm_provider
from src.api.chat.llm.base import LLMRole
from src.api.chat.metrics import (
    MESSAGE_DURATION_SECONDS,
    MESSAGES_TOTAL,
    SESSIONS_CREATED_TOTAL,
)
from src.api.chat.owner import extract_chat_owner
from src.api.chat.repository import ChatRepository, get_chat_repository
from src.api.chat.schemas import (
    ChatMessageResponse,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    CreateSessionInput,
    EscalateInput,
    EscalateResponse,
    FeedbackInput,
    SendMessageInput,
)
from src.api.chat.sse import format_sse_event
from src.api.chat.system_prompt import build_rag_system_prompt, hits_to_citations
from src.api.config import Settings, get_settings
from src.api.idempotency import IdempotencyResult
from src.api.search.repository import RetrievalHit
from src.api.search.retrieval import RetrievalService, get_retrieval_service
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)

logger = logging.getLogger(__name__)

# Rough token estimate для message-end / token_count в streaming. Совпадает
# с MockProvider's chars/4 heuristic; vLLM (E3.7) заменит на tokenizer count.
_CHARS_PER_TOKEN = 4

# Hardcoded mapping priority → estimated SLA (minutes). MVP-уровень;
# real values придут из E6 admin / kb-monitoring (наблюдаемая median
# response time из очереди тикетов).
_ESTIMATED_RESPONSE_BY_PRIORITY: dict[str, int] = {
    "low": 60,
    "normal": 30,
    "high": 10,
}

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=ChatSessionResponse,
    summary="Создать сессию чата",
)
async def create_session(
    response: Response,
    payload: CreateSessionInput | None = Body(default=None),
    owner: tuple[UUID | None, UUID | None] = Depends(extract_chat_owner),
    scope: Scope = Depends(get_current_scope),
    repo: ChatRepository = Depends(get_chat_repository),
) -> ChatSessionResponse:
    """`POST /chat/sessions` — создать новую сессию.

    Authorized (user_id из JWT sub): scope сохраняется как actual,
    `X-Chat-Session-Token` НЕ возвращается (client идентифицируется
    JWT'ом).

    Anonymous (no JWT или m2m sub не-UUID): scope='guest', server
    генерирует opaque `session_token`, возвращает в header
    `X-Chat-Session-Token`. Клиент обязан хранить этот токен и слать
    при последующих GET/DELETE.
    """
    user_id, _ = owner
    context = (
        payload.context.model_dump(mode="json")
        if payload is not None and payload.context is not None
        else {}
    )
    session = await repo.create_session(
        user_id=user_id,
        scope=scope.value,
        context=context,
    )

    SESSIONS_CREATED_TOTAL.labels(scope=scope.value).inc()

    if user_id is None:
        # Anon: возвращаем session_token в response header.
        # НЕ кладём в body (минимизация exposure secrets через JSON-логи).
        response.headers["X-Chat-Session-Token"] = str(session.session_token)

    return ChatSessionResponse.from_model(session)


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailResponse,
    summary="История сессии",
)
async def get_session_detail(
    session_id: UUID = Path(...),
    owner: tuple[UUID | None, UUID | None] = Depends(extract_chat_owner),
    repo: ChatRepository = Depends(get_chat_repository),
) -> ChatSessionDetailResponse:
    """`GET /chat/sessions/{id}` — session + messages.

    404 mask: out-of-scope ИЛИ not-exist — не различаем (ADR-0003
    adaptation). Owner-check через `get_session_by_owner` — без
    хотя бы одного identifier'а repository вернёт None.
    """
    user_id, session_token = owner
    session = await repo.get_session_by_owner(
        session_id, user_id=user_id, session_token=session_token
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await repo.list_messages(session_id, user_id=user_id, session_token=session_token)
    return ChatSessionDetailResponse.from_models(session, messages)


# RAG retrieval breadth для chat — меньше чем endpoint default (~10),
# т.к. длинный context block увеличивает LLM input tokens. 5 chunks ≈
# ~10K chars worst case, что вмещается в 8K-32K context window
# типичных open-weight моделей.
_RAG_CHAT_TOP_K = 5


async def _maybe_dispatch_no_answer(
    dispatcher: WebhookEventDispatcher,
    *,
    rag_enabled: bool,
    retrieved_chunks: list[RetrievalHit],
    session_id: UUID,
    query: str,
) -> None:
    """Fire `chat.no_answer` (ТЗ §5.1) когда RAG не нашёл relevant chunks.

    Fires только если:
    - `rag_enabled=True` — иначе chat не ожидался grounding'а через KB.
    - `retrieved_chunks == []` — нет sources для ответа.

    Payload per ТЗ §5.1 — `{session_id, query, retrieved_sources: []}`.

    Privacy note: `query` потенциально содержит ПДн (пользователь мог
    задать вопрос «как мне расторгнуть договор с Ивановым»). ТЗ явно
    включает `query` в payload — subscriber'ы (аналитика, KB coverage)
    обязаны быть в trusted scope (FZ-152 §6). Не logging'уем query в
    audit_log параллельно — webhook outbox единственный sink.

    Errors swallow'аются (chat не должен fail'ить на webhook side-effect).
    """
    if not rag_enabled or retrieved_chunks:
        return
    try:
        await dispatcher.dispatch(
            event_type="chat.no_answer",
            payload={
                "session_id": str(session_id),
                "query": query,
                "retrieved_sources": [],
            },
        )
    except Exception:
        # Defensive — webhook enqueue падать не должен (delivery_repo
        # сам log'ает swallow'нутые errors), но если упало внутри
        # subscriber-listing или dispatcher.dispatch — chat не падает.
        logger.exception(
            "chat.no_answer.dispatch_failed",
            extra={"session_id": str(session_id)},
        )


async def _retrieve_chunks_for_rag(
    *,
    enabled: bool,
    query: str,
    access_levels: frozenset[AccessLevel],
    retrieval: RetrievalService,
) -> list[RetrievalHit]:
    """Defensive retrieval для chat RAG.

    Возвращает [] если:
    - RAG_ENABLED=False (no-op).
    - Empty query / access_levels (defensive — `RetrievalService.search`
      уже handle'ит, но guard здесь делает behavior obvious).
    - Retrieval бросил exception — chat НЕ должен валиться от RAG'а
      (log + degraded mode без context).
    """
    if not enabled or not query.strip() or not access_levels:
        return []
    try:
        return await retrieval.search(
            query=query,
            access_levels=access_levels,
            top_k=_RAG_CHAT_TOP_K,
        )
    except Exception:
        logger.exception("chat.rag_retrieval_failed", extra={"query_len": len(query)})
        return []


def _build_llm_history(history_messages: list[object], new_user_content: str) -> list[LLMMessage]:
    """Конвертировать DB messages + new user content в LLMMessage list.

    `cast(LLMRole, ...)` — m.role в БД CHECK-constrained ∈ {user,
    assistant, system}, mypy не знает. Defensive: на безопасно широкий
    `object` ruff жалоб не будет, но runtime у Pydantic нет.
    """
    llm_messages: list[LLMMessage] = []
    for m in history_messages:
        role = cast(LLMRole, getattr(m, "role"))  # noqa: B009 — ORM attr
        content = cast(str, getattr(m, "content"))  # noqa: B009
        llm_messages.append(LLMMessage(role=role, content=content))
    llm_messages.append(LLMMessage(role="user", content=new_user_content))
    return llm_messages


async def _stream_message_events(
    session_id: UUID,
    user_content: str,
    history_messages: list[object],
    llm: LLMProvider,
    repo: ChatRepository,
    max_tokens: int,
    system_prompt: str,
    citations: list[dict[str, Any]],
    started: float,
) -> AsyncIterator[str]:
    """Generator для SSE streaming (E3.4).

    Events:
    - `message-start` (без message_id, см. architect deviation Issue #67)
    - `citations` (#136) — emitted после `message-start`, до first
      `chunk`. Frontend знает sources до начала streaming'а (UX win).
    - `chunk` per LLM yield
    - `error` если LLM exception (NO DB write)
    - `message-end` с message_id, total_tokens
    - `done`

    Retry-safety: chunks в memory, `record_chat_turn` только после
    успешного завершения LLM iteration.

    `started` — `time.perf_counter()` snapshot до handler dispatch.
    Histogram observed в finally — измеряет full SSE lifecycle вплоть до
    last yield (включая generator GC при early client disconnect).
    """
    try:
        yield format_sse_event(
            "message-start",
            {"created_at": datetime.now(UTC).isoformat()},
        )
        # `citations` всегда emit'ится (даже empty) — frontend опирается на
        # consistent event order. Empty список — explicit signal что RAG
        # disabled или не нашёл relevant chunks.
        yield format_sse_event("citations", {"data": citations})

        llm_messages = _build_llm_history(history_messages, user_content)
        chunks: list[str] = []
        try:
            async for chunk in llm.stream(llm_messages, system_prompt, max_tokens=max_tokens):
                chunks.append(chunk)
                yield format_sse_event("chunk", {"text": chunk})
        except Exception:
            # Defensive: НЕ эхо'им детали exception'а в SSE event
            # (могут содержать sensitive info от upstream LLM).
            logger.exception("chat.sse_stream_failed", extra={"session_id": str(session_id)})
            yield format_sse_event("error", {"message": "LLM upstream error"})
            return

        full_content = "".join(chunks)
        token_count = len(full_content) // _CHARS_PER_TOKEN

        # Atomic persist после успешного stream'а — retry-safe.
        assistant_msg = await repo.record_chat_turn(
            session_id,
            user_content=user_content,
            assistant_content=full_content,
            citations=citations,
            token_count=token_count,
            duration_ms=None,
        )

        yield format_sse_event(
            "message-end",
            {"message_id": str(assistant_msg.id), "total_tokens": token_count},
        )
        yield format_sse_event("done", {})
    finally:
        MESSAGE_DURATION_SECONDS.observe(time.perf_counter() - started)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatMessageResponse,
    summary="Отправить сообщение в чат (JSON или SSE)",
)
async def send_message(
    session_id: UUID = Path(...),
    payload: SendMessageInput = Body(...),
    accept: str = Header(default="application/json", alias="Accept"),
    owner: tuple[UUID | None, UUID | None] = Depends(extract_chat_owner),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ChatRepository = Depends(get_chat_repository),
    llm: LLMProvider = Depends(get_llm_provider),
    retrieval: RetrievalService = Depends(get_retrieval_service),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
    settings: Settings = Depends(get_settings),
) -> ChatMessageResponse | StreamingResponse:
    """`POST /chat/sessions/{id}/messages` — JSON или SSE mode.

    Branch по Accept header:
    - `text/event-stream` → SSE streaming (E3.4): yield chunks live,
      persist в конце.
    - `application/json` / `*/*` → JSON mode (E3.3): wait → return.

    Оба mode:
    1. Owner-gate session через `get_session_by_owner`. None → 404.
    2. Build conversation history.
    3. **RAG retrieve** (#136): если `RAG_ENABLED` — top-K chunks через
       `RetrievalService.search`, augment system prompt, attach citations.
       ADR-0003: `access_levels` определяют видимость chunk'ов.
    4. Call LLM с augmented system prompt (стриминг или complete).
    5. `record_chat_turn` — atomic INSERT обоих сообщений с citations.
    """
    user_id, session_token = owner
    session = await repo.get_session_by_owner(
        session_id, user_id=user_id, session_token=session_token
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    MESSAGES_TOTAL.labels(scope=session.scope).inc()
    started = time.perf_counter()

    history = await repo.list_messages(session_id, user_id=user_id, session_token=session_token)

    # RAG retrieval (#136) — defensive, returns [] если disabled/empty/error.
    retrieved_chunks = await _retrieve_chunks_for_rag(
        enabled=settings.rag_enabled,
        query=payload.content,
        access_levels=access_levels,
        retrieval=retrieval,
    )
    system_prompt = build_rag_system_prompt(retrieved_chunks)
    citations = hits_to_citations(retrieved_chunks)

    # #222 / ТЗ §5.1: fire `chat.no_answer` если RAG включён, но не
    # нашёл relevant chunks — signal для аналитики «нужен content gap fill».
    await _maybe_dispatch_no_answer(
        webhook_dispatcher,
        rag_enabled=settings.rag_enabled,
        retrieved_chunks=retrieved_chunks,
        session_id=session_id,
        query=payload.content,
    )

    if "text/event-stream" in accept.lower():
        # SSE mode (E3.4). Duration observed внутри generator'а в `finally`
        # (#181) — covers normal completion, LLM error path, и client
        # disconnect (early generator close).
        return StreamingResponse(
            _stream_message_events(
                session_id,
                payload.content,
                list(history),
                llm,
                repo,
                settings.llm_max_tokens,
                system_prompt,
                citations,
                started,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    # JSON mode (E3.3) — wait full completion.
    llm_messages = _build_llm_history(list(history), payload.content)
    response = await llm.complete(
        llm_messages,
        system_prompt,
        max_tokens=settings.llm_max_tokens,
    )
    assistant_msg = await repo.record_chat_turn(
        session_id,
        user_content=payload.content,
        assistant_content=response.content,
        citations=citations,
        token_count=response.token_count,
        duration_ms=response.duration_ms,
    )
    MESSAGE_DURATION_SECONDS.observe(time.perf_counter() - started)
    return ChatMessageResponse.from_model(assistant_msg)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить сессию (ФЗ-152 right-to-forget)",
)
async def delete_session(
    session_id: UUID = Path(...),
    owner: tuple[UUID | None, UUID | None] = Depends(extract_chat_owner),
    repo: ChatRepository = Depends(get_chat_repository),
) -> Response:
    """`DELETE /chat/sessions/{id}` — soft-delete.

    Идемпотентно: повторный DELETE → 404 (session уже невидима после
    soft-delete). Physical cleanup делает background worker (backlog).
    """
    user_id, session_token = owner
    deleted = await repo.soft_delete_session(
        session_id, user_id=user_id, session_token=session_token
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{session_id}/feedback",
    status_code=status.HTTP_201_CREATED,
    summary="Оставить фидбек на ответ ассистента",
)
async def post_feedback(
    session_id: UUID = Path(...),
    payload: FeedbackInput = Body(...),
    owner: tuple[UUID | None, UUID | None] = Depends(extract_chat_owner),
    repo: ChatRepository = Depends(get_chat_repository),
) -> Response:
    """`POST /chat/sessions/{id}/feedback` — feedback ratin/comment на message.

    Двухступенчатый owner-gate (E3.5 #69):
    1. session принадлежит caller'у (через `get_session_by_owner`).
    2. message принадлежит указанной session (`WHERE session_id =`).

    404 mask на любую из ошибок — клиент не различает причину.
    Idempotent: повторный POST с тем же message_id overwrite'ит feedback.
    """
    user_id, session_token = owner
    result = await repo.set_feedback(
        payload.message_id,
        session_id=session_id,
        user_id=user_id,
        session_token=session_token,
        rating=payload.rating,
        comment=payload.comment,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Session or message not found",
        )
    return Response(status_code=status.HTTP_201_CREATED)


@router.post(
    "/sessions/{session_id}/escalate",
    status_code=status.HTTP_201_CREATED,
    response_model=EscalateResponse,
    summary="Эскалация на оператора поддержки",
)
async def post_escalate(
    session_id: UUID = Path(...),
    payload: EscalateInput | None = Body(default=None),
    owner: tuple[UUID | None, UUID | None] = Depends(extract_chat_owner),
    repo: ChatRepository = Depends(get_chat_repository),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    idempotency: IdempotencyResult = Depends(process_chat_idempotency_key),
) -> Any:
    """`POST /chat/sessions/{id}/escalate` — создать ticket эскалации.

    Body optional: пустой POST → priority='normal', reason=None.

    Owner-gate через `create_escalation`. 404 mask если session не owned.

    Multiple escalations allowed — каждый POST создаёт новый ticket с
    уникальным id. Idempotency-Key (UUID header) делает endpoint retry-
    safe: повторный request с тем же key + body возвращает cached response
    (тот же ticket_id), no duplicate ticket / audit row / webhook fire.

    Webhook delivery в support system — backlog (E5 webhooks эпик).
    """
    if idempotency.replay is not None:
        # JSONResponse bypass'ит response_model re-validation на replay
        # path — защищает от schema drift между cached body и текущей
        # `EscalateResponse` shape (cache TTL = 24h, схема может
        # эволюционировать). Same pattern что в admin/users / articles.
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    user_id, session_token = owner
    reason = payload.reason if payload is not None else None
    priority = payload.priority if payload is not None else "normal"

    escalation = await repo.create_escalation(
        session_id,
        user_id=user_id,
        session_token=session_token,
        reason=reason,
        priority=priority,
    )
    if escalation is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # E4.x #104: audit trail. Actor:
    #   - JWT sub (UUID) для authenticated пользователей.
    #   - "anon:<session_token-prefix>" для anon-flow (нет PII в audit).
    actor_sub = str(user_id) if user_id is not None else format_anon_actor_sub(session_token)
    await audit_repo.record(
        actor_sub=actor_sub,
        action=ACTION_CHAT_ESCALATED,
        resource_type=RESOURCE_CHAT_SESSION,
        resource_id=str(session_id),
        metadata={
            "ticket_id": str(escalation.id),
            "priority": escalation.priority,
        },
    )

    # E5.3 #91: fire chat.escalated webhook.
    await webhook_dispatcher.dispatch(
        event_type="chat.escalated",
        payload={
            "ticket_id": str(escalation.id),
            "session_id": str(session_id),
            "priority": escalation.priority,
            "requested_at": escalation.requested_at.isoformat(),
        },
    )

    result = EscalateResponse(
        ticket_id=escalation.id,
        estimated_response_time_minutes=_ESTIMATED_RESPONSE_BY_PRIORITY[escalation.priority],
    )
    body = result.model_dump(mode="json")
    await idempotency.save(status_code=status.HTTP_201_CREATED, body=body)
    # JSONResponse напрямую — same pattern что и replay path; consistent
    # bypass response_model re-validation (cache TTL = 24h может пережить
    # schema drift).
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=body)

"""FastAPI router для `/api/v1/chat/sessions/*` (E3.2 #63).

3 эндпоинта:
- `POST /chat/sessions` — создать session (auth optional). Anon flow
  возвращает `X-Chat-Session-Token` header.
- `GET /chat/sessions/{id}` — owner-gated detail с messages.
- `DELETE /chat/sessions/{id}` — soft-delete (ФЗ-152 right-to-forget).

POST /messages, SSE, feedback, escalate — E3.3+.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Response, status
from fastapi.responses import StreamingResponse

from src.api.auth.dependency import get_current_scope
from src.api.auth.scope import Scope
from src.api.chat.llm import LLMMessage, LLMProvider, get_llm_provider
from src.api.chat.llm.base import LLMRole
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
from src.api.chat.system_prompt import SYSTEM_PROMPT
from src.api.config import Settings, get_settings

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
) -> AsyncIterator[str]:
    """Generator для SSE streaming (E3.4).

    Events:
    - `message-start` (без message_id, см. architect deviation Issue #67)
    - `chunk` per LLM yield
    - `error` если LLM exception (NO DB write)
    - `message-end` с message_id, total_tokens
    - `done`

    Retry-safety: chunks в memory, `record_chat_turn` только после
    успешного завершения LLM iteration.
    """
    yield format_sse_event(
        "message-start",
        {"created_at": datetime.now(UTC).isoformat()},
    )

    llm_messages = _build_llm_history(history_messages, user_content)
    chunks: list[str] = []
    try:
        async for chunk in llm.stream(llm_messages, SYSTEM_PROMPT, max_tokens=max_tokens):
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
        citations=[],
        token_count=token_count,
        duration_ms=None,
    )

    yield format_sse_event(
        "message-end",
        {"message_id": str(assistant_msg.id), "total_tokens": token_count},
    )
    yield format_sse_event("done", {})


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
    repo: ChatRepository = Depends(get_chat_repository),
    llm: LLMProvider = Depends(get_llm_provider),
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
    3. Call LLM (стриминг или complete).
    4. `record_chat_turn` — atomic INSERT обоих сообщений (после LLM).
    """
    user_id, session_token = owner
    session = await repo.get_session_by_owner(
        session_id, user_id=user_id, session_token=session_token
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    history = await repo.list_messages(session_id, user_id=user_id, session_token=session_token)

    if "text/event-stream" in accept.lower():
        # SSE mode (E3.4).
        return StreamingResponse(
            _stream_message_events(
                session_id,
                payload.content,
                list(history),
                llm,
                repo,
                settings.llm_max_tokens,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    # JSON mode (E3.3) — wait full completion.
    llm_messages = _build_llm_history(list(history), payload.content)
    response = await llm.complete(
        llm_messages,
        SYSTEM_PROMPT,
        max_tokens=settings.llm_max_tokens,
    )
    assistant_msg = await repo.record_chat_turn(
        session_id,
        user_content=payload.content,
        assistant_content=response.content,
        citations=[],
        token_count=response.token_count,
        duration_ms=response.duration_ms,
    )
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
) -> EscalateResponse:
    """`POST /chat/sessions/{id}/escalate` — создать ticket эскалации.

    Body optional: пустой POST → priority='normal', reason=None.

    Owner-gate через `create_escalation`. 404 mask если session не owned.

    Multiple escalations allowed — каждый POST создаёт новый ticket с
    уникальным id. Webhook delivery в support system — backlog
    (E5 webhooks эпик).
    """
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

    return EscalateResponse(
        ticket_id=escalation.id,
        estimated_response_time_minutes=_ESTIMATED_RESPONSE_BY_PRIORITY[escalation.priority],
    )

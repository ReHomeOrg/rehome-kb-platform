"""FastAPI router для `/api/v1/chat/sessions/*` (E3.2 #63).

3 эндпоинта:
- `POST /chat/sessions` — создать session (auth optional). Anon flow
  возвращает `X-Chat-Session-Token` header.
- `GET /chat/sessions/{id}` — owner-gated detail с messages.
- `DELETE /chat/sessions/{id}` — soft-delete (ФЗ-152 right-to-forget).

POST /messages, SSE, feedback, escalate — E3.3+.
"""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Response, status

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
    SendMessageInput,
)
from src.api.chat.system_prompt import SYSTEM_PROMPT
from src.api.config import Settings, get_settings

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


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatMessageResponse,
    summary="Отправить сообщение в чат (JSON mode)",
)
async def send_message(
    session_id: UUID = Path(...),
    payload: SendMessageInput = Body(...),
    accept: str = Header(default="application/json", alias="Accept"),
    owner: tuple[UUID | None, UUID | None] = Depends(extract_chat_owner),
    repo: ChatRepository = Depends(get_chat_repository),
    llm: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
) -> ChatMessageResponse:
    """`POST /chat/sessions/{id}/messages` — JSON-mode answer.

    Flow:
    1. Owner-gate session через `get_session_by_owner`. None → 404.
    2. Build conversation history (existing messages + new user content).
    3. Call LLMProvider.complete (БЕЗ DB writes — retry-safe).
    4. `record_chat_turn` — atomic INSERT обоих сообщений.
    5. Return assistant ChatMessageResponse.

    SSE streaming (Accept: text/event-stream) → 406 Not Acceptable
    с указанием на E3.4. После landing E3.4 — заменяем на actual streaming.
    """
    # SSE explicit request — НЕ поддержано в этом эпике (E3.4).
    # Точное совпадение accept ('text/event-stream') считаем явным запросом
    # SSE. `*/*` (browser default) — fallthrough к JSON.
    if "text/event-stream" in accept.lower():
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail=(
                "SSE streaming будет реализован в E3.4. "
                "Используйте Accept: application/json для JSON-mode."
            ),
        )

    user_id, session_token = owner
    session = await repo.get_session_by_owner(
        session_id, user_id=user_id, session_token=session_token
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build LLM history: существующие messages + новый user content.
    # NB: `get_session_by_owner` уже сделал owner-gate, повторно НЕ вызываем
    # `list_messages` через тот же gate — это лишний SQL. Делаем raw read.
    history = await repo.list_messages(session_id, user_id=user_id, session_token=session_token)
    # `m.role` — str из БД, но CHECK constraint гарантирует ∈ {user,
    # assistant, system}. cast() избегает mypy false-positive без
    # дополнительных runtime checks.
    llm_messages = [LLMMessage(role=cast(LLMRole, m.role), content=m.content) for m in history]
    llm_messages.append(LLMMessage(role="user", content=payload.content))

    # LLM call идёт ПЕРЕД любым DB write — если provider exception,
    # DB не тронута, клиент retry без duplicate.
    response = await llm.complete(
        llm_messages,
        SYSTEM_PROMPT,
        max_tokens=settings.llm_max_tokens,
    )

    # Atomic: user + assistant в одной транзакции.
    # citations всегда [] в E3.3 — RAG будет в kb-search эпике.
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

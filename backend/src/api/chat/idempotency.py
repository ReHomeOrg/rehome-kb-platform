"""Chat-specific `Idempotency-Key` dependency (#342 follow-up, see
`chat/repository.py::create_escalation` docstring backlog).

Чат-эндпоинты допускают anon flow (X-Chat-Session-Token), поэтому
обычный `process_idempotency_key` (требует JWT) не подходит. Здесь
делаем тот же flow, но `actor_sub` derives из `extract_chat_owner`:

- Authenticated: `actor_sub = str(user_id)` (UUID).
- Anon: `actor_sub = "anon:<token-prefix>"` — same shape что и в chat
  audit-log (`audit/actions.py::ANON_ACTOR_TOKEN_PREFIX_LEN`). Префикс
  достаточен для composite-PK uniqueness в idempotency_keys table
  + не утечкает full session_token в БД.
- No identifier (m2m sub не парсится в UUID, нет header) → idempotency
  no-op: header игнорируется, поведение как раньше (новый ticket
  на каждый POST).

Composite PK `(key, request_path, actor_sub)` гарантирует, что один
key между разными owner'ами не интерферирует.
"""

from uuid import UUID

from fastapi import Depends, Request

from src.api.audit.actions import ANON_ACTOR_TOKEN_PREFIX_LEN
from src.api.chat.owner import extract_chat_owner
from src.api.idempotency.dependency import (
    IdempotencyResult,
    _process_for_actor,
)
from src.api.idempotency.repository import (
    IdempotencyKeyRepository,
    get_idempotency_repository,
)


def _chat_actor_sub(user_id: UUID | None, session_token: UUID | None) -> str | None:
    """Derive actor_sub из owner pair. None если нет identifier'а
    (idempotency не активируется — header игнорируется)."""
    if user_id is not None:
        return str(user_id)
    if session_token is not None:
        return f"anon:{str(session_token)[:ANON_ACTOR_TOKEN_PREFIX_LEN]}"
    return None


async def process_chat_idempotency_key(
    request: Request,
    owner: tuple[UUID | None, UUID | None] = Depends(extract_chat_owner),
    repo: IdempotencyKeyRepository = Depends(get_idempotency_repository),
) -> IdempotencyResult:
    """Idempotency-Key dependency для chat anon/auth endpoints.

    Identical semantics с `process_idempotency_key` — replay при тот же
    body, 409 при mismatched body, 422 при невалидном UUID. Difference —
    actor derivation из chat owner вместо JWT claims.
    """
    user_id, session_token = owner
    actor_sub = _chat_actor_sub(user_id, session_token)
    if actor_sub is None:
        # Нет identifier'а — idempotency не применяется (нечего использовать
        # как PK actor_sub). Equivalent to header отсутствует.
        return IdempotencyResult.noop()
    return await _process_for_actor(request, repo, actor_sub)


__all__ = ["process_chat_idempotency_key"]

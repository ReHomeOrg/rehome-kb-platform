"""Извлечение identifier'ов владельца chat session из request (E3.2 #63).

Двойная авторизация (см. E3.1 #61):
- Authenticated user: `user_id = UUID(JWT.sub)` если sub парсится в UUID.
- Anonymous client: `session_token = UUID(X-Chat-Session-Token header)`.

Битые/несоответствующие UUID-format значения → `None` (graceful
degradation в anon flow). Это сознательное решение для m2m токенов,
у которых `sub` — это `service-account-<client-id>` (не UUID): чат
им технически не нужен, но мы не падаем 401 — даём им anon flow.

Логируем UUID-parse failures на DEBUG для диагностики (без эха
содержимого, чтобы не утечь secrets в логах).
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import Depends, Header

from src.api.auth.dependency import get_current_claims

logger = logging.getLogger(__name__)


def extract_chat_owner(
    claims: dict[str, Any] | None = Depends(get_current_claims),
    x_chat_session_token: str | None = Header(default=None, alias="X-Chat-Session-Token"),
) -> tuple[UUID | None, UUID | None]:
    """Извлекает `(user_id, session_token)` для chat-операций.

    None для каждого идентификатора, если соответствующего источника нет
    ИЛИ значение не парсится в UUID.

    **POST /sessions** допускает (None, None) — anon flow, server создаёт
    session_token и возвращает в response.

    **GET/DELETE /sessions/{id}** обязаны иметь хотя бы один identifier:
    `ChatRepository.get_session_by_owner` сам проверит и вернёт None →
    router отдаст 404 mask.
    """
    user_id: UUID | None = None
    if claims is not None:
        sub = claims.get("sub")
        if isinstance(sub, str):
            try:
                user_id = UUID(sub)
            except ValueError:
                # m2m sub типа `service-account-<client-id>` не UUID —
                # graceful degradation в anon flow. Логируем без эха.
                logger.debug("chat: JWT sub is not a UUID; falling back to anon flow")

    session_token: UUID | None = None
    if x_chat_session_token is not None:
        try:
            session_token = UUID(x_chat_session_token)
        except ValueError:
            # Битый header — игнорируем без 400 (клиент может прислать
            # session_token из прошлой жизни). Result: 404 mask на read,
            # либо новая session на POST.
            logger.debug("chat: X-Chat-Session-Token header is not a UUID")

    return user_id, session_token

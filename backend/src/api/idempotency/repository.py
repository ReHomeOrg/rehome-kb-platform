"""IdempotencyKeyRepository — единственная точка доступа к таблице (ADR-0008).

Lookup-or-create семантика реализована в `dependency.py` (lock-first
паттерн как в E5.0). Этот модуль — чистые CRUD-операции.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.idempotency.models import IdempotencyKey

# OpenAPI: «Ответ кешируется 24ч».
DEFAULT_TTL = timedelta(hours=24)


class IdempotencyKeyRepository:
    """Read+write для idempotency_keys.

    Поведение:
    - `acquire_lock(key, path, actor_sub)` — pg_advisory_xact_lock для
      serialize concurrent retries того же ключа (паттерн E5.0).
    - `get(...)` — lookup non-expired entry. Возвращает None если нет
      или истекла TTL.
    - `save(...)` — INSERT новой записи с TTL=24h.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_lock(self, key: str, path: str, actor_sub: str) -> None:
        """Postgres advisory xact lock на hash(key || path || actor_sub).

        Берётся ПЕРВЫМ в idempotency-dependency: ДО lookup. Это закрывает
        race window concurrent same-key (без lock-first два retry оба
        видят `None` в lookup → оба execute → дубликаты).

        Lock auto-релизится на commit/rollback (E5.0 паттерн).
        Postgres-specific.
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:composite))").bindparams(
                composite=f"{key}|{path}|{actor_sub}"
            )
        )

    async def get(self, key: str, path: str, actor_sub: str) -> IdempotencyKey | None:
        """Lookup non-expired entry."""
        now = datetime.now(UTC)
        stmt = select(IdempotencyKey).where(
            IdempotencyKey.key == key,
            IdempotencyKey.request_path == path,
            IdempotencyKey.actor_sub == actor_sub,
            IdempotencyKey.expires_at > now,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(
        self,
        *,
        key: str,
        path: str,
        actor_sub: str,
        request_body_hash: str,
        response_status: int,
        response_body: dict[str, Any],
        response_headers: dict[str, str],
    ) -> IdempotencyKey:
        """INSERT новую запись cache с TTL=24h + commit.

        Вызывается ПОСЛЕ успешного execution бизнес-логики (business code
        уже сделал свой commit). `save` коммитит явно — иначе при
        закрытии `get_session` контекста pending transaction откатится и
        idempotency-row не persistится (retry получит cache miss).

        Trade-off: commit отпускает advisory lock от dependency. Real-world
        race window между business-commit (lock release #1) и save-commit
        (lock release #2 + persist) минимален; concurrent retry до persist
        получит cache miss и execute'нет второй раз — то же что без E5.1.
        Полная защита — single-transaction-per-request (E5.x refactor).
        """
        entry = IdempotencyKey(
            key=key,
            request_path=path,
            actor_sub=actor_sub,
            request_body_hash=request_body_hash,
            response_status=response_status,
            response_body=response_body,
            response_headers=response_headers,
            expires_at=datetime.now(UTC) + DEFAULT_TTL,
        )
        self._session.add(entry)
        await self._session.commit()
        return entry


def get_idempotency_repository(
    session: AsyncSession = Depends(get_session),
) -> IdempotencyKeyRepository:
    """FastAPI Depends-factory."""
    return IdempotencyKeyRepository(session)

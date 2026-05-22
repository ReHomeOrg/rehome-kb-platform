"""Idempotency-Key dependency для FastAPI write endpoint'ов (E5.1 #44).

Паттерн использования в router:
```python
@router.post(...)
async def create_article(
    payload: ArticleInput,
    response: Response,
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
    # ... existing dependencies
):
    if idempotency.replay is not None:
        # Replay cached response.
        response.status_code = idempotency.replay.status
        for k, v in idempotency.replay.headers.items():
            response.headers[k] = v
        return idempotency.replay.body
    # Existing business logic.
    article = await repo.create(...)
    # ... save cache if key provided.
    await idempotency.save(status=201, body={...}, headers={"Location": ...})
    return result
```

См. Plan revision (Issue #44 comment 4430248568) для семантики.
"""

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request

from src.api.auth.dependency import require_authenticated
from src.api.idempotency.repository import (
    IdempotencyKeyRepository,
    get_idempotency_repository,
)


@dataclass(frozen=True)
class ReplayResponse:
    """Cached response для replay."""

    status: int
    body: dict[str, Any]
    headers: dict[str, str]


@dataclass(frozen=True)
class IdempotencyResult:
    """Возврат `process_idempotency_key`.

    - `replay` — если non-None, router должен вернуть cached response
      без выполнения бизнес-логики.
    - `key` — если non-None, idempotency mode активен; router должен
      вызвать `save(...)` после успешного execution.
    - `request_body_hash` — sha256(raw body); используется в save.

    Если `key is None` (header отсутствовал) → no-op mode: router
    выполняет логику как раньше, save игнорируется.
    """

    key: str | None
    request_body_hash: str | None
    replay: ReplayResponse | None
    _repo: IdempotencyKeyRepository | None
    _request_path: str | None
    _actor_sub: str | None

    @classmethod
    def noop(cls) -> "IdempotencyResult":
        return cls(
            key=None,
            request_body_hash=None,
            replay=None,
            _repo=None,
            _request_path=None,
            _actor_sub=None,
        )

    async def save(
        self,
        *,
        status_code: int,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Cache response для будущих retry'ев.

        No-op если key/repo не установлены (idempotency mode не активен).
        Вызывается ТОЛЬКО на success path router'а — 4xx/5xx не доходят
        сюда (exception bypass'ит save → fresh evaluation на retry per
        Stripe pattern).
        """
        if self.key is None or self._repo is None:
            return
        assert self._request_path is not None
        assert self._actor_sub is not None
        assert self.request_body_hash is not None
        await self._repo.save(
            key=self.key,
            path=self._request_path,
            actor_sub=self._actor_sub,
            request_body_hash=self.request_body_hash,
            response_status=status_code,
            response_body=body,
            response_headers=headers or {},
        )


async def _process_for_actor(
    request: Request,
    repo: IdempotencyKeyRepository,
    actor_sub: str,
) -> IdempotencyResult:
    """Shared core: assumes caller derived `actor_sub` (от auth flow или
    chat owner). Handles header presence, UUID validation, lock + lookup.

    Order (R2 plan revision):
    1. Parse + UUID validation.
    2. body_hash = sha256(await request.body()).
    3. acquire_lock (advisory xact).
    4. Lookup existing.
    5. Branch: replay / 409 / new.
    """
    raw_key = request.headers.get("Idempotency-Key")
    if raw_key is None:
        return IdempotencyResult.noop()

    # UUID validation (R3: UUID-only per OpenAPI format spec).
    try:
        UUID(raw_key)
    except ValueError as exc:
        # Numeric 422 — Starlette deprecate `HTTP_422_UNPROCESSABLE_ENTITY`
        # в пользу UNPROCESSABLE_CONTENT; используем литерал до E5.x align.
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must be a valid UUID",
        ) from exc

    request_path = request.url.path

    # R3: hash raw bytes (Stripe pattern). Starlette caches body — повторный
    # .body() возвращает те же bytes после Pydantic потребления.
    raw_body = await request.body()
    body_hash = sha256(raw_body).hexdigest()

    # R2: lock FIRST, потом lookup. Закрывает race concurrent same-key.
    await repo.acquire_lock(raw_key, request_path, actor_sub)

    existing = await repo.get(raw_key, request_path, actor_sub)
    if existing is not None:
        if existing.request_body_hash == body_hash:
            return IdempotencyResult(
                key=raw_key,
                request_body_hash=body_hash,
                replay=ReplayResponse(
                    status=existing.response_status,
                    body=existing.response_body,
                    headers=dict(existing.response_headers),
                ),
                _repo=repo,
                _request_path=request_path,
                _actor_sub=actor_sub,
            )
        # Same key, different body — 409 per Stripe.
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key reused with different request body",
        )

    return IdempotencyResult(
        key=raw_key,
        request_body_hash=body_hash,
        replay=None,
        _repo=repo,
        _request_path=request_path,
        _actor_sub=actor_sub,
    )


async def process_idempotency_key(
    request: Request,
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: IdempotencyKeyRepository = Depends(get_idempotency_repository),
) -> IdempotencyResult:
    """Dependency для Idempotency-Key header (authenticated callers).

    Сценарии:
    1. Header отсутствует → return `IdempotencyResult.noop()` (no-op).
    2. Header невалидный UUID → 422.
    3. Существует cache с тем же body_hash → return `IdempotencyResult`
       с `replay` (router immediate return).
    4. Существует cache с другим body_hash → 409 «reused with different body».
    5. Cache отсутствует → return `IdempotencyResult` с save_callback;
       router выполняет логику и потом сохраняет.

    `actor_sub` derives от JWT `sub` claim — cross-actor leakage protected
    через composite PK `(key, request_path, actor_sub)`. Для anon flow
    (chat /sessions/{id}/escalate) — см. `process_chat_idempotency_key`.
    """
    return await _process_for_actor(request, repo, claims["sub"])

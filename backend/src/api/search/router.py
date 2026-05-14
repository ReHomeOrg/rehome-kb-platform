"""FastAPI router для `POST /api/v1/search` (kb-search Stage 1, #134).

Финальный endpoint Stage 1: hybrid vector + BM25 + RRF retrieval поверх
RetrievalService (#132). Article-granularity output (dedupe по article_id;
best-score chunk wins) — соответствует OpenAPI `SearchHit` (id = article
UUID, title, snippet). Chunk-granularity для chat-grounding доступна
через `RetrievalService.search` напрямую (отдельный PR на chat
integration).

ADR-0003: access_level filter применён в `EmbeddingRepository.search` /
`ArticleRepository.search` — storage-level enforcement; обход
невозможен (см. PR #133 для invariant'а).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth.dependency import get_current_access_levels, require_authenticated
from src.api.auth.exceptions import UnauthorizedError
from src.api.auth.scope import AccessLevel
from src.api.search.repository import RetrievalHit
from src.api.search.retrieval import RetrievalService, get_retrieval_service
from src.api.search.schemas import SearchHit, SearchInput, SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


# Multiplier для top_k запроса: pull `limit * _DEDUPE_OVERFETCH_FACTOR`
# chunks от retrieval'а, dedupe'им по article_id, отдаём top `limit`.
# Anti-cluster: если top-N chunks от одной article'и — мы всё равно
# отдадим разнообразный набор article'й.
_DEDUPE_OVERFETCH_FACTOR = 3


@router.post(
    "",
    response_model=SearchResponse,
    summary="Универсальный поиск (hybrid vector + BM25 + RRF)",
    responses={
        401: {"description": "Не аутентифицирован"},
        422: {"description": "Невалидный body (query empty/whitespace, limit out of range)"},
    },
)
async def search(
    payload: SearchInput,
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    retrieval: RetrievalService = Depends(get_retrieval_service),
) -> SearchResponse:
    """POST /api/v1/search — hybrid retrieval по article kb.

    Flow:
    1. `require_authenticated` → 401 без токена.
    2. `get_current_access_levels` → `frozenset[AccessLevel]` из scope.
    3. Whitespace-only query → 422.
    4. Stage 1 фильтр types: если `types` указан и `"article"` не входит
       → empty data (нам нечего возвращать; document / premises_card /
       regulation за scope Stage 1).
    5. `RetrievalService.search` → list[RetrievalHit] (chunk-granularity).
    6. Dedupe по `article_id`: keep highest-score chunk per article.
    7. Top `limit` → `SearchHit[]` с clip score в [0, 1].
    """
    if not access_levels:
        # Defence-in-depth: должен поймать `require_authenticated`, но
        # на всякий случай (consistency с articles router).
        raise UnauthorizedError(detail="No access levels resolved")

    if not payload.query.strip():
        raise HTTPException(status_code=422, detail="query must not be whitespace-only")

    # Stage 1: только `article`. Если caller указал явный types без article
    # — он не ожидает результатов из этой Stage'и. Не error: forward-compat
    # (когда добавим document/etc, тот же caller сразу получит данные).
    if payload.types is not None and "article" not in payload.types:
        return SearchResponse(data=[])

    raw_hits = await retrieval.search(
        query=payload.query,
        access_levels=access_levels,
        top_k=payload.limit * _DEDUPE_OVERFETCH_FACTOR,
    )

    deduped = _dedupe_by_article(raw_hits)[: payload.limit]

    hits = [
        SearchHit(
            id=h.article_id,
            title=h.title,
            snippet=h.text,
            # RRF score ≤ 2/61 ≈ 0.033 на типичных кейсах; clip — defence
            # для OpenAPI [0, 1] contract'а.
            score=min(max(h.score, 0.0), 1.0),
            url=f"/articles/{h.slug}",
        )
        for h in deduped
    ]
    return SearchResponse(data=hits)


def _dedupe_by_article(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    """Сохранить самый score'ный chunk на article, preserving order.

    Хиты приходят отсортированными score desc (RRF в `_rrf_fuse`).
    Поэтому первое появление article'и — её best chunk; последующие
    chunks той же article'и отбрасываются.
    """
    seen: set[Any] = set()
    out: list[RetrievalHit] = []
    for h in hits:
        if h.article_id in seen:
            continue
        seen.add(h.article_id)
        out.append(h)
    return out

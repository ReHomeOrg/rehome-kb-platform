"""FastAPI router для `/api/v1/tags` (E2.6 #52).

Endpoint публичный (`security: []` в OpenAPI 04). При отсутствии JWT
client получает теги только из PUBLIC статей; при наличии — расширенный
scope через `get_current_access_levels` (ADR-0003 storage-level filter
применяется в TagRepository).
"""

from fastapi import APIRouter, Depends, Query

from src.api.auth.dependency import get_current_access_levels
from src.api.auth.scope import AccessLevel
from src.api.tags.repository import TagRepository, get_tag_repository
from src.api.tags.schemas import TagResponse, TagsListResponse

# Bounds для query parameters. limit clamp [1..200] — anti-DoS на
# агрегацию; q max_length=100 — sane bound на substring (длиннее не
# имеет смысла для real-world tags).
LIMIT_MIN = 1
LIMIT_MAX = 200
LIMIT_DEFAULT = 50
Q_MAX_LENGTH = 100


def _normalize_q(raw: str | None) -> str | None:
    """Empty / whitespace-only `q` → None (фильтр не применяется)."""
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


router = APIRouter(prefix="/tags", tags=["Tags"])


@router.get(
    "",
    response_model=TagsListResponse,
    summary="Список тегов",
)
async def list_tags(
    q: str | None = Query(default=None, max_length=Q_MAX_LENGTH),
    limit: int = Query(default=LIMIT_DEFAULT, ge=LIMIT_MIN, le=LIMIT_MAX),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: TagRepository = Depends(get_tag_repository),
) -> TagsListResponse:
    """`GET /api/v1/tags?q=&limit=` — публичный список тегов с article_count.

    Спецификация OpenAPI 04 `/api/v1/tags`. Сортировка `article_count DESC,
    name ASC`. ADR-0003: storage-level access_level filter — guest
    видит только PUBLIC теги, logged users — расширенный scope.
    """
    rows = await repo.list_tags(
        access_levels,
        q=_normalize_q(q),
        limit=limit,
    )
    return TagsListResponse(
        data=[TagResponse(name=name, article_count=count) for name, count in rows]
    )

"""FastAPI router для `/api/v1/articles/*`.

E2.1 — только `GET /articles/{slug}`. Дальнейшие операции (list, поиск,
write) добавляются в следующих эпиках через дополнительные методы router.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.articles.schemas import (
    ArticleResponse,
    ArticlesListResponse,
    ArticleSummary,
    PaginationInfo,
)
from src.api.auth.dependency import get_current_access_levels
from src.api.auth.exceptions import UnauthorizedError
from src.api.auth.scope import AccessLevel

# Slug pattern из OpenAPI / ADR-0006: lowercase ASCII, цифры, дефисы.
# 1..200 символов, не пустой. Защищает от path-injection и SQL-сюрпризов
# (хотя ORM параметризует — это defence-in-depth).
SLUG_PATTERN = r"^[a-z0-9-]+$"

router = APIRouter(prefix="/articles", tags=["Articles"])


@router.get(
    "",
    response_model=ArticlesListResponse,
    summary="Список статей с фильтрами и cursor-пагинацией",
    responses={
        400: {"description": "Невалидный cursor"},
        422: {"description": "Невалидные query-параметры (limit/audience/...)"},
    },
)
async def list_articles(
    category: str | None = Query(default=None, max_length=100),
    audience: str | None = Query(default=None, max_length=16),
    language: str | None = Query(default=None, max_length=8),
    cursor: str | None = Query(
        default=None,
        description="Opaque pagination cursor; не парсится клиентом.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleRepository = Depends(get_article_repository),
) -> ArticlesListResponse:
    """Отдаёт страницу опубликованных статей с фильтрацией по scope.

    ADR-0003: 404-маскировка тут не применяется — для list пустой массив
    нормален и не утекает информацию о существовании ресурсов другого
    scope (фильтр `access_level IN (...)` отсекает на SQL).
    """
    if not access_levels:
        raise UnauthorizedError(detail="No access levels resolved")

    decoded_cursor = decode_cursor(cursor) if cursor else None

    rows, has_more = await repo.list_filtered(
        access_levels,
        category=category,
        audience=audience,
        language=language,
        cursor=decoded_cursor,
        limit=limit,
    )

    cursor_next: str | None = None
    if rows and has_more:
        last = rows[-1]
        cursor_next = encode_cursor(last.updated_at, last.id)

    return ArticlesListResponse(
        data=[ArticleSummary.model_validate(row) for row in rows],
        pagination=PaginationInfo(cursor_next=cursor_next, has_more=has_more),
    )


@router.get(
    "/{slug}",
    response_model=ArticleResponse,
    summary="Получить статью по slug",
    responses={
        404: {"description": "Статья не существует или недоступна текущему scope"},
    },
)
async def get_article_by_slug(
    slug: str = Path(
        ...,
        min_length=1,
        max_length=200,
        pattern=SLUG_PATTERN,
        description="Канонический идентификатор статьи (ADR-0006)",
    ),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleRepository = Depends(get_article_repository),
) -> ArticleResponse:
    """Отдаёт опубликованную статью с фильтрацией по access_level.

    ADR-0008: router принимает `ArticleRepository`, не `AsyncSession` —
    storage-level фильтр (ADR-0003) защищён type-system'ом от случайного
    обхода через прямой `session.execute(...)`.

    Маскировка: если статья существует, но scope её не видит, возвращаем 404
    (не 403) — клиент не должен узнавать факт существования закрытого ресурса.
    """
    if not access_levels:
        # Defence-in-depth: compute_access_levels всегда возвращает минимум
        # {PUBLIC}, попадание сюда — баг scope-логики. Лучше 401 чем 500.
        raise UnauthorizedError(detail="No access levels resolved")

    article = await repo.get_by_slug(slug, access_levels)
    if article is None:
        # 404 не 403 (ADR-0003 masking).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )
    return ArticleResponse.model_validate(article)

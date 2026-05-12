"""FastAPI router для `/api/v1/articles/*`.

E2.1 — только `GET /articles/{slug}`. Дальнейшие операции (list, поиск,
write) добавляются в следующих эпиках через дополнительные методы router.
"""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.repository import ArticleRepository
from src.api.articles.schemas import ArticleResponse
from src.api.auth.dependency import get_current_access_levels
from src.api.auth.exceptions import UnauthorizedError
from src.api.auth.scope import AccessLevel
from src.api.db import get_session

# Slug pattern из OpenAPI / ADR-0006: lowercase ASCII, цифры, дефисы.
# 1..200 символов, не пустой. Защищает от path-injection и SQL-сюрпризов
# (хотя ORM параметризует — это defence-in-depth).
SLUG_PATTERN = r"^[a-z0-9-]+$"

router = APIRouter(prefix="/articles", tags=["Articles"])


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
    session: AsyncSession = Depends(get_session),
) -> ArticleResponse:
    """Отдаёт опубликованную статью с фильтрацией по access_level.

    ADR-0003: на пустой набор access_levels отдаём 401 (анонимный пользователь
    видит только PUBLIC через `compute_access_levels([])` — `frozenset` всегда
    содержит как минимум PUBLIC; пустой результат означает баг конфигурации).

    Маскировка: если статья существует, но scope её не видит, возвращаем 404
    (не 403) — клиент не должен узнавать факт существования закрытого ресурса.
    """
    if not access_levels:
        # Defence-in-depth: compute_access_levels всегда возвращает минимум
        # {PUBLIC}, попадание сюда — баг scope-логики. Лучше 401 чем 500.
        raise UnauthorizedError(detail="No access levels resolved")

    repo = ArticleRepository(session)
    article = await repo.get_by_slug(slug, access_levels)
    if article is None:
        # 404 не 403 (ADR-0003 masking).
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )
    return ArticleResponse.model_validate(article)

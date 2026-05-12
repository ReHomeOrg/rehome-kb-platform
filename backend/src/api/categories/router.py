"""FastAPI router для `/api/v1/categories` (E2.7 #54).

Public endpoint (`security: []` в OpenAPI 04). При отсутствии JWT
client получает article_count только из PUBLIC статей; при наличии —
расширенный scope. Структура дерева возвращается всегда — даже когда
scope не видит ни одной статьи (полезно для UX навигации).
"""

from fastapi import APIRouter, Depends

from src.api.auth.dependency import get_current_access_levels
from src.api.auth.scope import AccessLevel
from src.api.categories.repository import (
    CategoryNode,
    CategoryRepository,
    get_category_repository,
)
from src.api.categories.schemas import CategoriesListResponse, CategoryResponse

router = APIRouter(prefix="/categories", tags=["Categories"])


def _node_to_response(node: CategoryNode) -> CategoryResponse:
    """Конверсия из internal CategoryNode → public CategoryResponse.

    Рекурсивная — каждый child становится CategoryResponse со своим
    списком children. `id`/`parent_id` НЕ exposes (внутренние UUID;
    клиент работает по slug).
    """
    return CategoryResponse(
        slug=node.slug,
        title=node.title,
        description=node.description,
        article_count=node.article_count,
        children=[_node_to_response(c) for c in node.children],
    )


@router.get(
    "",
    response_model=CategoriesListResponse,
    summary="Дерево категорий",
)
async def list_categories(
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: CategoryRepository = Depends(get_category_repository),
) -> CategoriesListResponse:
    """`GET /api/v1/categories` — публичное дерево категорий.

    Спецификация OpenAPI 04 `/api/v1/categories`. Сортировка на каждом
    уровне: `article_count DESC, slug ASC`. ADR-0003: article_count
    считается только из видимых для scope статей.
    """
    roots = await repo.list_tree(access_levels)
    return CategoriesListResponse(data=[_node_to_response(n) for n in roots])

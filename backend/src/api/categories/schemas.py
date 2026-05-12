"""Pydantic схемы для `/api/v1/categories`.

Recursive `CategoryResponse.children: list[CategoryResponse]` — Pydantic
2.x резолвит forward ref автоматически после `model_rebuild()`. Вызов
в конце модуля гарантирует, что схема готова к использованию из router.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CategoryResponse(BaseModel):
    """Одна категория в дереве.

    Соответствует OpenAPI 04 `components/schemas/Category`. `description`
    optional (исходно nullable в БД). `children` — массив того же типа;
    при отсутствии дочерних — пустой список (не omitted), чтобы клиенту
    не приходилось различать «нет children» и «детей нет».
    """

    slug: str
    title: str
    description: str | None = None
    article_count: int = Field(ge=0)
    children: list[CategoryResponse] = Field(default_factory=list)


CategoryResponse.model_rebuild()


class CategoriesListResponse(BaseModel):
    """Ответ для `GET /api/v1/categories`."""

    data: list[CategoryResponse]

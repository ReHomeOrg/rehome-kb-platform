"""Pydantic схемы для `/api/v1/tags`.

Соответствует OpenAPI 04 `components/schemas/Tag` (line ~3024).
Response envelope (`meta` обёртка) — единый E5 рефакторинг покроет
все endpoints; пока возвращаем голый `{data: [...]}` как в articles.
"""

from pydantic import BaseModel, Field


class TagResponse(BaseModel):
    """Одна запись в списке тегов."""

    name: str
    article_count: int = Field(ge=0)


class TagsListResponse(BaseModel):
    """Ответ для `GET /api/v1/tags`."""

    data: list[TagResponse]

"""Pydantic schemas для Article API.

Соответствуют OpenAPI `Article` (минимальное подмножество E2.1).
Расширения (related, version_history, seo_metadata) — в будущих PR.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ArticleResponse(BaseModel):
    """Полный ответ для `GET /articles/{slug}`.

    Pydantic v2 + `from_attributes=True` — позволяет model_validate
    напрямую из SQLAlchemy ORM объекта.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    summary: str | None = None
    body_markdown: str
    audience: str
    # OpenAPI ArticleSummary требует access_level в каждом ответе.
    # Это безопасно: пользователь и так получил статью, значит видит её
    # уровень. Информация полезна клиенту для UI badge «Только для staff».
    # Поля audience/status/language пока str (drift от OpenAPI enum
    # допустим до E4 — там добавим Pydantic enum-валидацию).
    access_level: str
    language: str
    category: str
    tags: list[str]
    status: str
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ArticleSummary(BaseModel):
    """Краткая карточка статьи для list endpoint (без `body_markdown`).

    Соответствует OpenAPI `ArticleSummary` (минимальный набор полей,
    `short_answer` пока опущен — поле в моделях отсутствует).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    category: str
    audience: str
    access_level: str
    tags: list[str]
    status: str
    updated_at: datetime


class PaginationInfo(BaseModel):
    """Курсор-пагинация. `cursor_prev` и `total_estimate` будут добавлены
    позже (см. Issue #25 «Out of scope») — partial drift от OpenAPI.
    """

    cursor_next: str | None = None
    has_more: bool = False


class ArticlesListResponse(BaseModel):
    """Ответ для `GET /api/v1/articles`.

    OpenAPI оборачивает в `ResponseEnvelope {meta, data, pagination}` —
    мы пока без `meta` (единый E5 рефакторинг покроет все endpoints).
    """

    data: list[ArticleSummary]
    pagination: PaginationInfo

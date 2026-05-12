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

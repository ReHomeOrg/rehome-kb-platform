"""Pydantic schemas для Article API.

Соответствуют OpenAPI `Article` (минимальное подмножество E2.1).
Расширения (related, version_history, seo_metadata) — в будущих PR.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.api.auth.scope import AccessLevel


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


class ArticleInput(BaseModel):
    """Payload для `POST /api/v1/articles`.

    Соответствует OpenAPI `ArticleInput` со следующими deviation'ами от спеки:
    - `access_level` — обязательное (OpenAPI: optional). Approved by
      Architect в Issue #27 (issuecomment 4428692249). Backlog для спеки — #28.
    - `extra='forbid'` — неизвестные поля отвергаются (защита от мусора в
      payload и потенциальных side-channel'ов).
    - `audience` — `str` без enum-валидации Pydantic'ом (drift OpenAPI как
      в read-API; CHECK constraint в БД защищает; E4.x — единый enum-rollout).
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1, max_length=200)
    body_markdown: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=100)
    audience: str = Field(min_length=1, max_length=16)
    # Pydantic v2 + StrEnum → автоматическая 422 если значение не в enum.
    # Это покрывает N2 из ревью плана: ValueError не уходит в 500.
    access_level: AccessLevel
    status: str = Field(default="DRAFT", min_length=1, max_length=16)
    language: str = Field(default="ru", min_length=1, max_length=8)
    tags: list[str] = Field(default_factory=list)


class ArticleVersionResponse(BaseModel):
    """История изменений статьи (OpenAPI `ArticleVersion`).

    `author` — Keycloak `sub` claim (UUID), не human-readable имя
    (spec evolution одобрено в Issue #36 issuecomment 4429626012).
    `event` — тип события, породившего эту версию (additive в OpenAPI).
    Content (body_markdown/title) НЕ хранится — backlog для compliance.

    NB: router строит этот response из ORM `ArticleVersion`, мапя
    `author_sub → author` явно (а не через alias/from_attributes) — чтобы
    field name в API чётко совпадал с OpenAPI и не зависел от Pydantic
    alias-конфигурации FastAPI.
    """

    version: int
    author: str
    changed_at: datetime
    event: str
    changes_summary: str | None = None


class ArticleHistoryResponse(BaseModel):
    """Ответ `GET /api/v1/articles/{slug}/history` — массив версий."""

    data: list[ArticleVersionResponse]


class ArticlePatch(BaseModel):
    """Partial-update payload для `PATCH /api/v1/articles/{slug}`.

    Соответствует OpenAPI `ArticlePatch` (строки 2909-2926) с двумя уточнениями:
    - `short_answer` опущен (поле отсутствует в БД; backlog для миграции).
    - `access_level`, `slug`, `category`, `audience`, `language` запрещены
      через `extra='forbid'`: смена visibility/identifier требует PUT с
      явным target check. Это security-by-design (writer не может тихо
      повысить access_level через PATCH).

    Используется в repository через `model_dump(exclude_unset=True)` —
    только явно переданные поля попадают в UPDATE. Различие
    «не передано» vs «явно null» сохраняется (future-proof; пока nullable
    полей нет).
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_markdown: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = Field(default=None)
    # `status` пока str (drift OpenAPI, как audience в ArticleInput) —
    # backlog #28 для enum-rollout. DB CHECK всё равно отсечёт невалид.
    status: str | None = Field(default=None, min_length=1, max_length=16)


class SearchInput(BaseModel):
    """Body для `POST /api/v1/articles/search` (OpenAPI E2.5a #46).

    `q` — обязателен, 1..500 chars. Пустая строка отвергается через
    `min_length=1`; whitespace-only отвергается через validator.
    """

    model_config = ConfigDict(extra="forbid")

    q: str = Field(min_length=1, max_length=500)
    cursor: str | None = Field(default=None)
    limit: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    """SearchHit per OpenAPI (схема 3443-3473) минимальное подмножество.

    `type='article'` для E2.5a (document/premises_card/regulation — другие
    домены). `score` — `ts_rank` от 0; OpenAPI говорит 0..1, raw `ts_rank`
    обычно < 1 на типичных запросах; clip к 1.0 в роутере если превышает.

    **Snippet WARNING**: `ts_headline` оборачивает совпадения в `<b>...</b>`
    но НЕ escape'нет existing HTML в `body_markdown`. Frontend ОБЯЗАН
    sanitize (например, через DOMPurify) перед `dangerouslySetInnerHTML`.
    """

    type: str = "article"
    id: UUID
    title: str
    snippet: str | None = None
    score: float = Field(ge=0, le=1)


class ArticlesSearchResponse(BaseModel):
    """Ответ `POST /api/v1/articles/search`.

    Cursor стабильный только для **того же `q`**: rank query-dependent;
    при смене query — fresh search (client должен отбрасывать cursor).
    """

    data: list[SearchHit]
    pagination: PaginationInfo

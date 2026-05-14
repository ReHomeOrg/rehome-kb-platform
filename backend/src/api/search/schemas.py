"""Pydantic schemas для `POST /api/v1/search` (kb-search Stage 1, #134).

Соответствуют OpenAPI `POST /api/v1/search` + `SearchHit` (lines 1055-1110,
3532-3561). Stage 1 поддерживает только `type=article`; types document /
premises_card / regulation accept'ятся но возвращают empty (forward-compat).
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SearchInput(BaseModel):
    """Body для `POST /api/v1/search` (OpenAPI lines 1075-1096).

    `query` — 1..500 chars; whitespace-only отвергается через validator
    в router'е (Pydantic min_length=1 не ловит `"   "`).
    `types` — список enum'ов; в Stage 1 фактически фильтрует только
    `article` (другие → empty в response, не error).
    `limit` — top-K результатов после fusion; 1..50.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    types: list[Literal["article", "document", "premises_card", "regulation"]] | None = None
    limit: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    """Один результат search per OpenAPI `SearchHit` schema.

    Поля:
    - `type` — для Stage 1 всегда `"article"`.
    - `id` — article UUID (article-granularity, не chunk).
    - `title` — denormalized из Article (single roundtrip в SQL).
    - `snippet` — chunk text (лучший chunk для article'и после dedupe);
      raw markdown, **frontend ОБЯЗАН sanitize через DOMPurify** перед
      `dangerouslySetInnerHTML`.
    - `score` — RRF fused; clip к [0, 1] для OpenAPI conformance.
    - `url` — `/articles/{slug}`; deep-link для frontend nav.
    """

    type: Literal["article"] = "article"
    id: UUID
    title: str
    snippet: str | None = None
    score: float = Field(ge=0, le=1)
    url: str


class SearchResponse(BaseModel):
    """Top-level response: `{data: SearchHit[]}` (без cursor pagination —
    `POST /api/v1/search` per OpenAPI возвращает single page top-K)."""

    data: list[SearchHit]

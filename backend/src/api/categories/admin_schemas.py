"""Admin CRUD schemas for /admin/categories (ADR-0024, #355).

`CategoryCreate` — POST body.
`CategoryPatch` — PATCH body (slug READ-ONLY per ADR §Open Qs).
`CategoryView` — GET/POST/PATCH response.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Slug pattern matches existing `CategoryRepository` invariants —
# kebab-case lowercase ASCII / digits / hyphens.
_SLUG_PATTERN = r"^[a-z0-9-]+$"


class CategoryCreate(BaseModel):
    """POST /admin/categories body.

    Slug — immutable identifier (ADR-0024 §Open Q 2: slug READ-ONLY).
    Title — human-readable. Description optional.
    `parent_id` optional — None = root category.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=100, pattern=_SLUG_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: UUID | None = None


class CategoryPatch(BaseModel):
    """PATCH /admin/categories/{id} body.

    Slug — НЕ в schema (ADR-0024 §Open Q 2: immutable; меняет articles.category
    string references). Editable: title, description, parent_id.
    Cycle detection — server-side (см. `CategoryAdminRepository.update`).
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: UUID | None = None


class CategoryView(BaseModel):
    """Admin response — включает archived_at для admin tree view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    description: str | None
    parent_id: UUID | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


__all__ = ["CategoryCreate", "CategoryPatch", "CategoryView"]

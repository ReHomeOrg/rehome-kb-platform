"""Pydantic схемы для `/api/v1/webhooks` (E5.1 #87).

Source: OpenAPI 04 components/schemas (line 3542-3590).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from src.api.webhooks.events import ALLOWED_EVENTS


class WebhookInput(BaseModel):
    """Payload для POST /webhooks."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    events: list[str] = Field(min_length=1)
    secret: str | None = Field(default=None, min_length=8, max_length=64)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("events")
    @classmethod
    def _validate_events(cls, v: list[str]) -> list[str]:
        for event in v:
            if event not in ALLOWED_EVENTS:
                raise ValueError(f"Unknown event: {event!r}. Allowed: {sorted(ALLOWED_EVENTS)}")
        return v


class WebhookResponse(BaseModel):
    """Webhook в response. Включает все поля Webhook (id, client_id,
    created_at, last_delivery_*). Secret exposes ТОЛЬКО при создании
    (POST 201), при последующих GET — секрет можно либо вырезать
    (зависит от security policy), либо оставить, поскольку owner —
    тот же client.
    """

    id: UUID
    client_id: str
    url: str
    events: list[str]
    secret: str
    description: str | None
    created_at: datetime
    last_delivery_at: datetime | None
    last_delivery_status: int | None

    @classmethod
    def from_model(cls, webhook: Any) -> "WebhookResponse":
        return cls(
            id=webhook.id,
            client_id=webhook.client_id,
            url=webhook.url,
            events=webhook.events,
            secret=webhook.secret,
            description=webhook.description,
            created_at=webhook.created_at,
            last_delivery_at=webhook.last_delivery_at,
            last_delivery_status=webhook.last_delivery_status,
        )


class WebhooksListResponse(BaseModel):
    """Ответ для GET /webhooks."""

    data: list[WebhookResponse]

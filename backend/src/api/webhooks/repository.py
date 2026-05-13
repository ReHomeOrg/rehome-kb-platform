"""WebhookRepository (E5.1 #87).

Owner-scoped — все методы фильтруют по `client_id` (JWT sub). Cross-owner
access невозможен (404 mask).

ADR-0008 — Repository pattern.
"""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.webhooks.models import Webhook


def generate_secret() -> str:
    """HMAC secret — 32 bytes URL-safe (≈43 chars)."""
    return secrets.token_urlsafe(32)


class WebhookRepository:
    """Storage layer для webhook subscriptions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        client_id: str,
        url: str,
        events: list[str],
        secret: str | None = None,
        description: str | None = None,
    ) -> Webhook:
        """Создать webhook. Если `secret` is None — генерируется."""
        webhook = Webhook(
            client_id=client_id,
            url=url,
            events=events,
            secret=secret if secret else generate_secret(),
            description=description,
        )
        self._session.add(webhook)
        await self._session.flush()
        await self._session.refresh(webhook)
        await self._session.commit()
        return webhook

    async def list_by_owner(self, client_id: str) -> list[Webhook]:
        """Только active (deleted_at IS NULL) webhooks owner'а."""
        stmt = (
            select(Webhook)
            .where(
                Webhook.client_id == client_id,
                Webhook.deleted_at.is_(None),
            )
            .order_by(Webhook.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_subscribers(self, event_type: str) -> list[Webhook]:
        """Active webhooks подписанные на `event_type` (любого owner'а).

        Используется dispatcher'ом при срабатывании trigger'а — события
        системные, не привязаны к актёру (Stripe/GitHub pattern).
        """
        # `events @> ARRAY[event_type]` — array contains element (PG operator).
        stmt = select(Webhook).where(
            Webhook.deleted_at.is_(None),
            Webhook.events.contains([event_type]),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id_and_owner(self, webhook_id: UUID, client_id: str) -> Webhook | None:
        """404 mask — owner mismatch ИЛИ deleted → None."""
        stmt = (
            select(Webhook)
            .where(
                Webhook.id == webhook_id,
                Webhook.client_id == client_id,
                Webhook.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(self, webhook_id: UUID, client_id: str) -> bool:
        """Soft-delete: устанавливает deleted_at. Идемпотентно.

        Возвращает True если deletion произошёл, False если webhook не
        найден / уже удалён / не принадлежит client_id.
        """
        webhook = await self.get_by_id_and_owner(webhook_id, client_id)
        if webhook is None:
            return False
        webhook.deleted_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.commit()
        return True


def get_webhook_repository(
    session: AsyncSession = Depends(get_session),
) -> WebhookRepository:
    return WebhookRepository(session)

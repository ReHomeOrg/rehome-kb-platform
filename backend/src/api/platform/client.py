"""HTTP-клиент платформы reHome (rehome.one) для help-центра.

Валидирует платформенный `rh_token` через `GET /auth/me/` (on-behalf-of юзера) и
— опционально — тянет статус онбординга через internal m2m-эндпоинт по ТЕЛЕФОНУ
(`X-Internal-Service-Key`). Всё best-effort: любой сбой платформы → None, help
деградирует до анонимного вида, но не падает.

ФЗ-152: телефон и токен — ПДн/секрет, в логи не пишем (максимум — факт неудачи).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.api.config import Settings

logger = logging.getLogger(__name__)


class PlatformClient:
    """Тонкий httpx-клиент к платформенному API (только нужные help-центру вызовы)."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.platform_api_url.rstrip("/")
        self._key = settings.internal_service_key
        self._timeout = settings.platform_timeout_seconds

    async def get_me(self, rh_token: str) -> dict[str, Any] | None:
        """Платформенный юзер по `rh_token` (Bearer) или None если токен невалиден."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base}/auth/me/",
                    headers={"Authorization": f"Bearer {rh_token}"},
                )
        except httpx.HTTPError as err:
            logger.warning("platform.get_me request failed: %s", err)
            return None
        if resp.status_code != 200:
            return None
        return self._json_dict(resp)

    async def get_onboarding_status(self, *, phone: str, role: str) -> dict[str, Any] | None:
        """Статус онбординга по ТЕЛЕФОНУ через internal m2m-эндпоинт (best-effort).

        Требует INTERNAL_SERVICE_KEY; без ключа возвращает None (обогащение
        пропускается, recognition при этом продолжает работать).
        """
        if not self._key:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base}/internal/onboarding/status/",
                    params={"phone_number": phone, "role": role},
                    headers={"X-Internal-Service-Key": self._key},
                )
        except httpx.HTTPError as err:
            logger.warning("platform.onboarding request failed: %s", err)
            return None
        if resp.status_code != 200:
            return None
        return self._json_dict(resp)

    @staticmethod
    def _json_dict(resp: httpx.Response) -> dict[str, Any] | None:
        try:
            data = resp.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

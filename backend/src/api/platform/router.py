"""Мост личности платформы для help-центра — `POST /api/v1/auth/platform-session`.

Help-центр (Next.js под rehome.one/help) читает платформенный cookie `rh_token`
(тот же домен) и зовёт этот endpoint server-to-server, прокидывая токен заголовком
`X-RH-Token`. Backend валидирует токен через platform `/auth/me/` и (опц.) обогащает
статусом онбординга по телефону. Возвращает компактный статус для рендера шапки
(скрыть «Войти», показать имя) — БЕЗ ПДн сверх имени пользователя.

Секреты (INTERNAL_SERVICE_KEY) держим на backend — фронт их не видит. Флаг
`PLATFORM_SESSION_ENABLED` по умолчанию off: пока не выставлен — endpoint отдаёт
`authenticated=false` (прод-поведение help неизменно).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.api.config import Settings, get_settings
from src.api.platform.client import PlatformClient

router = APIRouter(tags=["Auth"])


class PlatformSessionResponse(BaseModel):
    """Компактный статус платформенной сессии для рендера шапки help-центра."""

    authenticated: bool
    display_name: str | None = None
    onboarding_complete: bool | None = None
    next_path: str | None = None


def _display_name(me: dict[str, Any]) -> str | None:
    name = " ".join(str(p) for p in (me.get("first_name"), me.get("last_name")) if p)
    return name or None


@router.post("/auth/platform-session", summary="Признать залогиненного на платформе юзера")
async def platform_session(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> PlatformSessionResponse:
    """По платформенному `rh_token` вернуть, залогинен ли посетитель на rehome.one."""
    if not settings.platform_session_enabled:
        return PlatformSessionResponse(authenticated=False)

    rh_token = request.headers.get("X-RH-Token") or request.cookies.get("rh_token")
    if not rh_token:
        return PlatformSessionResponse(authenticated=False)

    client = PlatformClient(settings)
    me = await client.get_me(rh_token)
    if me is None:
        return PlatformSessionResponse(authenticated=False)

    phone = me.get("phone_number")
    onboarding = await client.get_onboarding_status(phone=phone, role="owner") if phone else None

    return PlatformSessionResponse(
        authenticated=True,
        display_name=_display_name(me),
        onboarding_complete=(onboarding.get("complete") if onboarding else None),
        next_path=(onboarding.get("next_path") if onboarding else None),
    )

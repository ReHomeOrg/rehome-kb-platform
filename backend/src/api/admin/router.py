"""FastAPI router для `/api/v1/admin/*` (#227+).

Endpoints landed:
- #227: GET /admin/stats
- #228: GET /admin/llm/providers

Backlog: users / system-config / security-incidents / personal-data /
llm/active (PUT) / llm/eval-runs / cache / reindex / tasks/{id}.

RBAC: все admin endpoints требуют `staff_admin` (STAFF + LEGAL) per
OpenAPI «Доступ — staff_admin». В коде это означает: caller имеет
AccessLevel.STAFF И AccessLevel.LEGAL (см. `_serialize_for_scope`
pattern в collaborators router — same admin-set heuristic).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.admin.llm_providers import build_provider_catalog
from src.api.admin.schemas import (
    AdminStats,
    AdminStatsChat,
    AdminStatsContent,
    AdminStatsPeriod,
    AdminStatsSecurity,
    LlmProvidersListResponse,
)
from src.api.admin.stats_repository import (
    AdminStatsRepository,
    get_admin_stats_repository,
)
from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.config import Settings, get_settings

router = APIRouter(prefix="/admin", tags=["Admin"])


# Per ТЗ §3.X / OpenAPI: «Окно — последние 30 дней по умолчанию».
_DEFAULT_WINDOW_DAYS = 30
# Hard cap на window length — anti-DoS на больших scan'ах.
_MAX_WINDOW_DAYS = 365


def _require_staff_admin(access_levels: frozenset[AccessLevel]) -> None:
    """staff_admin scope (STAFF + LEGAL) per OpenAPI.

    staff_support (только STAFF) или staff_hr (STAFF + HR_RESTRICTED)
    → 403. Это намеренно: admin/stats показывает security/PD metrics,
    их видит только staff_admin / staff_legal по ADR-0003.
    """
    if not (AccessLevel.STAFF in access_levels and AccessLevel.LEGAL in access_levels):
        raise HTTPException(
            status_code=403,
            detail="Требуется staff_admin или staff_legal scope",
        )


@router.get(
    "/stats",
    response_model=AdminStats,
    response_model_by_alias=True,
    summary="Сводная статистика kb-модуля (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
        422: {"description": "Window > 365 дней"},
    },
)
async def get_admin_stats(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: AdminStatsRepository = Depends(get_admin_stats_repository),
) -> AdminStats:
    """`GET /api/v1/admin/stats` (OpenAPI 04 §getAdminStats).

    Window:
    - Default — last 30 days (now-30d .. now).
    - Custom via `from` / `to` query params.
    - Max window — 365 days (anti-DoS).

    Возвращает 4 sub-блока:
    - `content` — articles/documents counts (snapshot, не window'ed).
    - `chat` — sessions/messages/escalations/avg_rating (window'ed).
    - `requests` — HTTP-level метрики; Prometheus только, MVP=zeros
      (см. schemas docstring).
    - `security` — incidents/PD-requests; таблиц ещё нет, MVP=zeros.

    Honest stubs: frontend получает определённый shape всегда, даже
    если backend feature ещё не реализован. Это лучше чем 404'ить
    sub-блоки (admin UI ломается).
    """
    _require_staff_admin(access_levels)

    now = datetime.now(UTC)
    period_to = to or now
    period_from = from_ or (period_to - timedelta(days=_DEFAULT_WINDOW_DAYS))

    if period_from > period_to:
        raise HTTPException(status_code=422, detail="'from' must be ≤ 'to'")
    if (period_to - period_from).days > _MAX_WINDOW_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Window exceeds {_MAX_WINDOW_DAYS} days (anti-DoS)",
        )

    # Content — snapshot (всё, что published сейчас).
    total_articles, draft_articles = await repo.count_articles_total_and_drafts()
    total_documents = await repo.count_documents_total()

    # Chat — window'ed aggregates.
    sessions = await repo.count_chat_sessions(from_=period_from, to=period_to)
    messages = await repo.count_chat_messages(from_=period_from, to=period_to)
    escalations = await repo.count_chat_escalations(from_=period_from, to=period_to)
    up_count, total_feedback = await repo.chat_rating_up_and_total(from_=period_from, to=period_to)

    containment_rate = 0.0 if sessions == 0 else 1.0 - (escalations / sessions)
    # Clip [0, 1] на случай если escalations > sessions (race / edge).
    containment_rate = min(max(containment_rate, 0.0), 1.0)

    avg_rating: float | None = None
    if total_feedback > 0:
        avg_rating = up_count / total_feedback

    return AdminStats(
        period=AdminStatsPeriod(from_=period_from, to=period_to),
        content=AdminStatsContent(
            total_articles=total_articles,
            total_documents=total_documents,
            pending_reviews=draft_articles,
        ),
        chat=AdminStatsChat(
            sessions=sessions,
            messages=messages,
            containment_rate=containment_rate,
            avg_rating=avg_rating,
            no_answer_count=0,  # see schemas docstring — webhook-only event
            escalations=escalations,
        ),
        # `requests` / `security` — defaults (zeros). См. schemas.py для
        # документации почему: данных в БД пока нет.
        security=AdminStatsSecurity(),
    )


# ---------------------------------------------------------------------------
# LLM providers (#228, OpenAPI 04 §listLlmProviders)


@router.get(
    "/llm/providers",
    response_model=LlmProvidersListResponse,
    summary="Список подключённых LLM-провайдеров (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
    },
)
async def list_llm_providers(
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    settings: Settings = Depends(get_settings),
) -> LlmProvidersListResponse:
    """`GET /api/v1/admin/llm/providers` (OpenAPI 04 §listLlmProviders).

    Возвращает 4 known providers (mock, vllm, gigachat, yandex_gpt) с
    `is_current=true` для текущего `LLM_PROVIDER` env-config'а.

    Используется admin UI для feature-flag переключения через PUT
    /admin/llm/active (backlog). Eval-стенд (см. Чат-поиск ТЗ v2 §3)
    использует endpoint чтобы перечислить available providers для
    benchmark runs.

    Cost rates / health checks — null в response (no authoritative
    backend source; см. schemas docstring + llm_providers.py).
    """
    _require_staff_admin(access_levels)
    return LlmProvidersListResponse(data=build_provider_catalog(settings))


__all__ = ["router"]

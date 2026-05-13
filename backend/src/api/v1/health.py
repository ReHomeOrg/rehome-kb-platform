"""Health, version, ready endpoints.

`/health` — liveness probe (process работает). `/ready` (#112) — readiness
probe с DB ping: 200 если app может обслуживать запросы, 503 если нет.

См. OpenAPI: `docs/handoff/01_postanovka/04_openapi.yaml` пути `/api/v1/health`
и `/api/v1/version` (security: []).
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import get_settings
from src.api.db import get_session
from src.api.observability.context import get_request_id

router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)


@router.get("/health", summary="Liveness probe")
def health() -> dict[str, str]:
    """200 OK всегда, если процесс работает."""
    return {"status": "ok"}


@router.get("/version", summary="Версия API")
def version() -> dict[str, str]:
    """Метаданные сборки: версия API, git commit, дата сборки, окружение."""
    settings = get_settings()
    return {
        "api_version": settings.api_version,
        "build_hash": settings.git_commit,
        "build_date": settings.build_date,
        "environment": settings.environment,
    }


async def _ping_db(session: AsyncSession, timeout_seconds: float) -> None:
    """Cheap `SELECT 1` с timeout — readiness signal что DB reachable."""
    await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=timeout_seconds)


@router.get(
    "/ready",
    summary="Readiness probe",
    responses={
        200: {"description": "App ready: DB reachable."},
        503: {"description": "Dependency not ready (e.g., DB unreachable)."},
    },
)
async def ready(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """200 OK если DB ping succeed'ит в пределах timeout; иначе 503.

    Body shape соответствует OpenAPI 04 (status + dependencies map): легко
    расширяется когда landed'ятся Keycloak/MinIO/Qdrant.

    ФЗ-152: exception details НЕ в response body — только enum'ы down/ok.
    Detail доступен в structured logs (с request_id).
    """
    settings = get_settings()
    try:
        await _ping_db(session, settings.readiness_db_timeout_seconds)
        return {"status": "ready", "dependencies": {"db": "ok"}}
    except Exception as exc:
        logger.warning(
            "ready.db_check_failed",
            extra={
                "error": str(exc),
                "request_id": get_request_id(),
            },
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "dependencies": {"db": "down"}}

"""Health, version, ready endpoints.

`/ready` появится после E1.3 (Keycloak/auth) и E1.4+ (Postgres/Qdrant/MinIO),
когда будут реальные зависимости для проверки. На E1.1 — только `/health`
(всегда 200) и `/version` (метаданные сборки).

См. OpenAPI: `docs/handoff/01_postanovka/04_openapi.yaml` пути `/api/v1/health`
и `/api/v1/version` (security: []).
"""

from fastapi import APIRouter

from src.api.config import get_settings

router = APIRouter(tags=["Health"])


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

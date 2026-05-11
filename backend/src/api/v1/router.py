"""v1 API router aggregator.

Подключает sub-routers модулей kb-*. На E1.1 — только health.
Дальнейшие модули (articles, documents, premises-cards, chat и т.д.)
добавляются через `router.include_router(...)` в рамках своих эпиков.
"""

from fastapi import APIRouter

from src.api.v1 import health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)

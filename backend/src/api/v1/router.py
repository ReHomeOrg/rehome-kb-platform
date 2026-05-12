"""v1 API router aggregator.

Подключает sub-routers модулей kb-*. На E1.1 — только health.
На E1.3.2 добавлен /whoami. На E2.1 добавлен /articles.
На E2.6 (#52) добавлен /tags. Дальнейшие модули (documents,
premises-cards, chat и т.д.) добавляются через
`router.include_router(...)` в рамках своих эпиков.
"""

from fastapi import APIRouter

from src.api.articles.router import router as articles_router
from src.api.categories.router import router as categories_router
from src.api.tags.router import router as tags_router
from src.api.v1 import auth, health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(articles_router)
router.include_router(tags_router)
router.include_router(categories_router)

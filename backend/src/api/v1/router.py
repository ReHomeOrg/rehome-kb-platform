"""v1 API router aggregator.

Подключает sub-routers модулей kb-*. На E1.1 — только health.
На E1.3.2 добавлен /whoami. На E2.1 добавлен /articles.
На E2.6 (#52) добавлен /tags. Дальнейшие модули (documents,
premises-cards, chat и т.д.) добавляются через
`router.include_router(...)` в рамках своих эпиков.
"""

from fastapi import APIRouter

from src.api.articles.router import router as articles_router
from src.api.audit.router import router as audit_router
from src.api.categories.router import router as categories_router
from src.api.chat.router import router as chat_router
from src.api.collaborators.junction_router import router as premises_collaborators_router
from src.api.collaborators.metrics_router import router as collaborator_metrics_router
from src.api.collaborators.reviews_router import router as collaborator_reviews_router
from src.api.collaborators.router import router as collaborators_router
from src.api.documents.router import router as documents_router
from src.api.hr.router import router as hr_router
from src.api.premises.router import router as premises_router
from src.api.search.router import router as search_router
from src.api.tags.router import router as tags_router
from src.api.v1 import auth, health
from src.api.vault.router import router as vault_router
from src.api.webhooks.router import router as webhooks_router

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(articles_router)
router.include_router(audit_router)
router.include_router(tags_router)
router.include_router(categories_router)
router.include_router(documents_router)
router.include_router(collaborators_router)
router.include_router(collaborator_reviews_router)
router.include_router(collaborator_metrics_router)
router.include_router(premises_collaborators_router)
router.include_router(chat_router)
router.include_router(search_router)
router.include_router(premises_router)
router.include_router(hr_router)
router.include_router(vault_router)
router.include_router(webhooks_router)

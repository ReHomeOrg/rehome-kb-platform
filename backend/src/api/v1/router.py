"""v1 API router aggregator.

Подключает sub-routers модулей kb-*. На E1.1 — только health.
На E1.3.2 добавлен /whoami. На E2.1 добавлен /articles.
На E2.6 (#52) добавлен /tags. Дальнейшие модули (documents,
premises-cards, chat и т.д.) добавляются через
`router.include_router(...)` в рамках своих эпиков.
"""

from fastapi import APIRouter

from src.api.admin.audit_log_router import router as admin_audit_log_router
from src.api.admin.eval_runs_router import router as admin_eval_runs_router
from src.api.admin.operational_router import router as admin_operational_router
from src.api.admin.pd_requests_router import router as admin_pd_requests_router
from src.api.admin.router import router as admin_router
from src.api.admin.security_incidents_router import (
    router as admin_security_incidents_router,
)
from src.api.admin.users_router import router as admin_users_router
from src.api.articles.questions_router import admin_router as article_questions_admin_router
from src.api.articles.questions_router import public_router as article_questions_public_router
from src.api.articles.router import router as articles_router
from src.api.audit.router import router as audit_router
from src.api.categories.admin_router import router as admin_categories_router
from src.api.categories.router import router as categories_router
from src.api.chat.router import router as chat_router
from src.api.collaborators.junction_router import router as premises_collaborators_router
from src.api.collaborators.metrics_router import router as collaborator_metrics_router
from src.api.collaborators.reviews_router import router as collaborator_reviews_router
from src.api.collaborators.router import router as collaborators_router
from src.api.collaborators.service_orders_router import router as service_orders_router
from src.api.documents.router import router as documents_router
from src.api.hr.router import router as hr_router
from src.api.premises.router import router as premises_router
from src.api.search.router import router as search_router
from src.api.tags.router import router as tags_router
from src.api.v1 import auth, health
from src.api.vault.emergency_router import (
    admin_router as vault_emergency_admin_router,
)
from src.api.vault.emergency_router import (
    owner_router as vault_emergency_owner_router,
)
from src.api.vault.fido2_router import router as vault_fido2_router
from src.api.vault.router import router as vault_router
from src.api.webhooks.router import router as webhooks_router

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(articles_router)
router.include_router(article_questions_public_router)
router.include_router(article_questions_admin_router)
router.include_router(audit_router)
router.include_router(tags_router)
router.include_router(categories_router)
router.include_router(documents_router)
router.include_router(collaborators_router)
router.include_router(collaborator_reviews_router)
router.include_router(collaborator_metrics_router)
router.include_router(premises_collaborators_router)
router.include_router(service_orders_router)
router.include_router(chat_router)
router.include_router(search_router)
router.include_router(premises_router)
router.include_router(hr_router)
router.include_router(vault_router)
router.include_router(vault_fido2_router)
router.include_router(vault_emergency_owner_router)
router.include_router(vault_emergency_admin_router)
router.include_router(webhooks_router)
router.include_router(admin_router)
router.include_router(admin_users_router)
router.include_router(admin_categories_router)
router.include_router(admin_security_incidents_router)
router.include_router(admin_pd_requests_router)
router.include_router(admin_audit_log_router)
router.include_router(admin_operational_router)
router.include_router(admin_eval_runs_router)

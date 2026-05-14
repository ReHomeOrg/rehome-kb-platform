"""kb-premises module (PZ §5).

Foundation: read-side endpoints для карточек квартир. Write side +
per-tenant access + frontend — follow-up PR'ы.
"""

from src.api.premises.models import PremisesCard
from src.api.premises.repository import PremisesRepository, get_premises_repository
from src.api.premises.router import router as premises_router
from src.api.premises.schemas import (
    PremisesListResponse,
    PremisesSummary,
    PremisesView,
    project_for_scope,
)

__all__ = [
    "PremisesCard",
    "PremisesListResponse",
    "PremisesRepository",
    "PremisesSummary",
    "PremisesView",
    "get_premises_repository",
    "premises_router",
    "project_for_scope",
]

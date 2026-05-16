"""Collaborators module — единая сущность для внешних исполнителей платформы.

ТЗ §10, API §3.10, ADR-0014. Slice 1 — foundation + CRUD.
"""

from src.api.collaborators.access import (
    COLLABORATOR_TYPES,
    FINANCIAL_GROUPS,
    STATUSES,
    TYPE_TO_FINANCIAL_GROUP,
    compute_visible_groups,
    derive_financial_group,
)
from src.api.collaborators.models import Collaborator
from src.api.collaborators.repository import (
    CollaboratorRepository,
    get_collaborator_repository,
)

__all__ = [
    "COLLABORATOR_TYPES",
    "FINANCIAL_GROUPS",
    "STATUSES",
    "TYPE_TO_FINANCIAL_GROUP",
    "Collaborator",
    "CollaboratorRepository",
    "compute_visible_groups",
    "derive_financial_group",
    "get_collaborator_repository",
]

"""kb-auth module: OIDC validation and scope/access_level computation.

См. ADR-0003 (двухконтурность), ADR-0007 (Keycloak realm structure).
"""

from src.api.auth.exceptions import (
    ForbiddenError,
    InvalidTokenError,
    UnauthorizedError,
)
from src.api.auth.scope import (
    SCOPE_TO_ACCESS_LEVELS,
    AccessLevel,
    Scope,
    compute_access_levels,
    compute_scope,
)

__all__ = [
    "SCOPE_TO_ACCESS_LEVELS",
    "AccessLevel",
    "ForbiddenError",
    "InvalidTokenError",
    "Scope",
    "UnauthorizedError",
    "compute_access_levels",
    "compute_scope",
]

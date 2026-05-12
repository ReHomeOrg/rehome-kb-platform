"""Auth-specific fixtures (используются только в tests/unit/auth/).

Shared JWT/JWKS machinery поднята в `tests/unit/conftest.py` после E4.1 —
нужна также articles write-тестам.
"""

import pytest

from src.api.auth.oidc import OIDCVerifier
from src.api.config import Settings


@pytest.fixture
def verifier(test_settings: Settings) -> OIDCVerifier:
    return OIDCVerifier(test_settings)

"""kb-vault module (#146, ADR-0011).

Zero-knowledge менеджер паролей. Foundation cube — storage layer.
Endpoints (unlock / CRUD / share) — cube 1.2. Frontend (WebCrypto +
Argon2id WASM) — cube 1.3.
"""

from src.api.vault.models import (
    VaultGroup,
    VaultGroupMember,
    VaultSecret,
    VaultSecretBlob,
    VaultSecretWrap,
    VaultUser,
)
from src.api.vault.repository import VaultRepository, get_vault_repository
from src.api.vault.router import router as vault_router

__all__ = [
    "VaultGroup",
    "VaultGroupMember",
    "VaultRepository",
    "VaultSecret",
    "VaultSecretBlob",
    "VaultSecretWrap",
    "VaultUser",
    "get_vault_repository",
    "vault_router",
]

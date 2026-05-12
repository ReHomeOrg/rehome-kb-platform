"""Application configuration loaded from environment variables.

См. README.md → раздел «Переменные окружения». Все значения имеют дефолты,
поэтому приложение запускается «из коробки» без `.env` (что нужно для CI и
для smoke-теста после `make run`).
"""

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the kb-API gateway."""

    api_version: str = Field(default="1.0.0-alpha", alias="REHOME_API_VERSION")
    git_commit: str = Field(default="unknown", alias="GIT_COMMIT")
    build_date: str = Field(default="unknown", alias="BUILD_DATE")
    environment: str = Field(default="dev", alias="REHOME_ENV")

    # Keycloak / OIDC settings. См. ADR-0007.
    keycloak_url: str = Field(default="http://localhost:8080", alias="KC_URL")
    keycloak_realm: str = Field(default="rehome", alias="KC_REALM")
    # Реальный `aud` для m2m токенов обеспечивается audience mapper в
    # realm-export.json (см. infra/keycloak/realm-export.json clients[0]).
    # Issue #21 (E1.3.4) добавил mapper и включил verify_aud по умолчанию.
    keycloak_audience: str = Field(default="rehome-platform-m2m", alias="KC_AUDIENCE")
    verify_aud: bool = Field(default=True, alias="KC_VERIFY_AUD")

    # PostgreSQL для articles/documents/... (ADR-0008). Отдельная БД от
    # Keycloak'овской (postgres-keycloak). asyncpg-драйвер обязателен для
    # async SQLAlchemy.
    database_url: str = Field(
        default="postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb",
        alias="DATABASE_URL",
    )

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        populate_by_name=True,
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def keycloak_issuer(self) -> str:
        """OIDC issuer URL для проверки `iss` claim."""
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def keycloak_jwks_url(self) -> str:
        """JWKS endpoint для получения публичных ключей realm."""
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"


def get_settings() -> Settings:
    """Build a fresh Settings instance (reads env at call time).

    Намеренно не кэшируется: значения env могут меняться в тестах через
    `monkeypatch.setenv`, и каждое чтение `/version` отражает текущее
    окружение. Производительности это не вредит — endpoint вызывается редко.
    """
    return Settings()

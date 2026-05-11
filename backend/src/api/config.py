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
    keycloak_audience: str = Field(default="account", alias="KC_AUDIENCE")
    # На E1.3.2 audience-проверка отключена до integration теста с реальным
    # Keycloak (E1.3.4). TODO(#17 follow-up): после E1.3.4 включить True.
    verify_aud: bool = Field(default=False, alias="KC_VERIFY_AUD")

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

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

    # LLM provider selection (E3 Chat MVP). 'mock' для dev/test
    # (детерминистический echo), 'vllm' — production self-hosted
    # (адаптер в E3.7). Unknown value — ValueError из factory.
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    llm_max_tokens: int = Field(default=1024, alias="LLM_MAX_TOKENS")

    # vLLM adapter settings (E3.7 #73). Используются только когда
    # llm_provider='vllm'. Default URL — `localhost:8000` для dev;
    # production должен переопределить через env.
    llm_vllm_url: str = Field(default="http://localhost:8000", alias="LLM_VLLM_URL")
    llm_vllm_model: str = Field(default="Qwen/Qwen2.5-7B-Instruct", alias="LLM_VLLM_MODEL")
    llm_vllm_timeout_seconds: int = Field(default=60, alias="LLM_VLLM_TIMEOUT_SECONDS")
    llm_vllm_api_key: str | None = Field(default=None, alias="LLM_VLLM_API_KEY")

    # Webhook delivery worker (E5.2 #89). Worker запускается в FastAPI
    # lifespan если enabled=True. В test environment (pytest) — flag
    # должен быть False (default), чтобы asyncio loops не мешали.
    webhook_worker_enabled: bool = Field(default=False, alias="WEBHOOK_WORKER_ENABLED")
    webhook_worker_poll_interval_seconds: float = Field(
        default=5.0, alias="WEBHOOK_WORKER_POLL_INTERVAL_SECONDS"
    )
    webhook_delivery_timeout_seconds: float = Field(
        default=10.0, alias="WEBHOOK_DELIVERY_TIMEOUT_SECONDS"
    )
    webhook_max_attempts: int = Field(default=5, alias="WEBHOOK_MAX_ATTEMPTS")
    webhook_backoff_base_seconds: float = Field(default=30.0, alias="WEBHOOK_BACKOFF_BASE_SECONDS")

    # Observability (#108). `/metrics` endpoint включается явно — safe-by-default
    # для случая, когда reverse-proxy ещё не настроен фильтровать его наружу.
    # MetricsMiddleware всегда работает (counter/histogram дешёвые); только
    # эндпоинт gate'ится.
    metrics_enabled: bool = Field(default=False, alias="METRICS_ENABLED")

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

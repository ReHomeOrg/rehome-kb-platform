"""Application configuration loaded from environment variables.

См. README.md → раздел «Переменные окружения». Все значения имеют дефолты,
поэтому приложение запускается «из коробки» без `.env` (что нужно для CI и
для smoke-теста после `make run`).
"""

from typing import Literal

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
    # ADR-0019 §"X-MFA-Token validation" / RFC 9470 step-up auth. Token's
    # `acr` claim must equal this value to gate MFA-protected admin
    # endpoints (PATCH /admin/system-config, PUT /admin/llm/active).
    # Keycloak default `acr=2` means MFA-verified; some realms emit
    # `aal2` / `loa2` — override per realm.
    kc_mfa_required_acr: str = Field(default="2", alias="KC_MFA_REQUIRED_ACR")

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

    # GigaChat adapter settings (RU LLM провайдер от Сбера). Использует
    # OAuth client_credentials → access_token caching → chat completions.
    # ТЗ §1.2 — Russian sovereignty (ФЗ-152: данные не покидают РФ).
    llm_gigachat_client_id: str | None = Field(default=None, alias="LLM_GIGACHAT_CLIENT_ID")
    llm_gigachat_client_secret: str | None = Field(default=None, alias="LLM_GIGACHAT_CLIENT_SECRET")
    llm_gigachat_oauth_url: str = Field(
        default="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        alias="LLM_GIGACHAT_OAUTH_URL",
    )
    llm_gigachat_base_url: str = Field(
        default="https://gigachat.devices.sberbank.ru", alias="LLM_GIGACHAT_BASE_URL"
    )
    llm_gigachat_model: str = Field(default="GigaChat", alias="LLM_GIGACHAT_MODEL")
    llm_gigachat_scope: str = Field(default="GIGACHAT_API_PERS", alias="LLM_GIGACHAT_SCOPE")
    llm_gigachat_timeout_seconds: int = Field(default=60, alias="LLM_GIGACHAT_TIMEOUT_SECONDS")
    # TLS verify: production использует Russian Trusted CA bundle (path
    # на disk). В dev/test можно отключить через verify=False (НЕ
    # рекомендуется production).
    llm_gigachat_verify_ssl: bool = Field(default=True, alias="LLM_GIGACHAT_VERIFY_SSL")

    # YandexGPT adapter settings (Yandex Cloud, RU sovereign). Использует
    # OpenAI-compatible endpoint /v1/chat/completions. Auth — Api-Key из
    # service account (Yandex Cloud Console). `model` resolves в
    # `gpt://<folder_id>/<model>/<version>` через factory.
    llm_yandex_api_key: str | None = Field(default=None, alias="LLM_YANDEX_API_KEY")
    llm_yandex_folder_id: str | None = Field(default=None, alias="LLM_YANDEX_FOLDER_ID")
    llm_yandex_base_url: str = Field(
        default="https://llm.api.cloud.yandex.net", alias="LLM_YANDEX_BASE_URL"
    )
    llm_yandex_model: str = Field(default="yandexgpt-lite", alias="LLM_YANDEX_MODEL")
    llm_yandex_model_version: str = Field(default="latest", alias="LLM_YANDEX_MODEL_VERSION")
    llm_yandex_timeout_seconds: int = Field(default=60, alias="LLM_YANDEX_TIMEOUT_SECONDS")

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

    # Log format (#110): `"text"` (default) — uvicorn-style для dev;
    # `"json"` — JSON-line per record для prod log aggregator'ов (Loki/ELK).
    # Literal'ом, чтобы pydantic-settings fail-fast на typo (LOG_FORMAT=jsno
    # → ValidationError на startup, а не silent fallback).
    log_format: Literal["text", "json"] = Field(default="text", alias="LOG_FORMAT")

    # Readiness probe (#112): max time to wait for DB ping before declaring
    # not-ready. 2s — conservative для default; k8s probe timeout обычно 3-5s.
    readiness_db_timeout_seconds: float = Field(default=2.0, alias="READINESS_DB_TIMEOUT_SECONDS")

    # kb-search / RAG (ADR-0010 Stage 1, #126). Default `RAG_ENABLED=False` —
    # foundation landed в off-state, явный flip когда indexer + endpoint
    # готовы. Эмбеддинги через self-hosted model (ФЗ-152: no external API).
    rag_enabled: bool = Field(default=False, alias="RAG_ENABLED")
    # Provider selection: 'mock' (default, deterministic SHA — для dev/tests),
    # 'hf' (sentence-transformers, production). HF provider land'ится в
    # follow-up; до тех пор `hf` режим fail-fast при startup.
    embedding_provider: Literal["mock", "hf"] = Field(
        default="mock",
        alias="EMBEDDING_PROVIDER",
    )
    embedding_model: str = Field(
        default="intfloat/multilingual-e5-large",
        alias="EMBEDDING_MODEL",
    )
    # Dim строго matches model output. Изменение требует pgvector column
    # migration — менять одновременно с model bump.
    embedding_dim: int = Field(default=1024, alias="EMBEDDING_DIM")

    # Cross-encoder re-ranking (ADR-0010 follow-up). `False` default —
    # retrieval работает через чистый RRF; при `True` поверх RRF top-N
    # запускается reranker (mock либо real cross-encoder). Latency cost
    # +50-200ms per request (depends на N и model size).
    rerank_enabled: bool = Field(default=False, alias="RERANK_ENABLED")
    rerank_provider: Literal["mock", "cross_encoder"] = Field(
        default="mock",
        alias="RERANK_PROVIDER",
    )
    # Default model — multilingual (RU + EN). Альтернатива: ms-marco-MiniLM-L-6-v2
    # для English-only deployments (~80 MB vs 280 MB).
    rerank_model: str = Field(
        default="BAAI/bge-reranker-base",
        alias="RERANK_MODEL",
    )
    # Сколько hits из RRF top-N passing через reranker. >top_k чтобы
    # reranker мог промотить далёкие RRF hits если они более relevant.
    rerank_top_n: int = Field(default=20, alias="RERANK_TOP_N")

    # Documents object storage (ADR-0012, TZ §3.4). MinIO/S3-compatible.
    # `minio_enabled=False` default: read endpoint возвращает 503 пока ops
    # не сконфигурируют MinIO; integration tests включают true с docker
    # compose service.
    minio_enabled: bool = Field(default=False, alias="MINIO_ENABLED")
    minio_endpoint: str = Field(default="localhost:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="", alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="rehome-kb-files", alias="MINIO_BUCKET")
    # `False` для local dev (HTTP); `True` для production (HTTPS).
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")
    # Per TZ §3.4 — TTL подписи 5 минут.
    signed_url_ttl_seconds: int = Field(default=300, alias="SIGNED_URL_TTL_SECONDS")
    # Phase B (ADR-0012): max payload для multipart upload, anti-DoS.
    # 50 MB — приемлемо для legal docs (типичный DOCX < 5MB, PDF < 20MB).
    # Большие файлы — backlog для multipart-init flow.
    document_max_upload_bytes: int = Field(
        default=50 * 1024 * 1024, alias="DOCUMENT_MAX_UPLOAD_BYTES"
    )

    # HR Stage 2 — ПДн encryption (ADR-0018). 32-byte url-safe base64
    # string (Fernet.generate_key() output). Dev default — fixed valid
    # Fernet key для tests / local dev. На production environment'е
    # этот sentinel detected как dev-key и fail'ит startup (см.
    # `hr/crypto.py` _DEV_KEY_SENTINEL check). Rotate per ADR-0018.
    hr_encryption_key: str = Field(
        default="DnshURO5oCxsHWvw5ECnPe75EVAJTPpv2ImjBOyUZmM=",
        alias="HR_ENCRYPTION_KEY",
    )
    # Optional legacy key для rotation: decrypt-only fallback когда
    # backend transition'ит на новый primary key. None = только primary.
    hr_encryption_key_legacy: str | None = Field(default=None, alias="HR_ENCRYPTION_KEY_LEGACY")

    # FIDO2 / WebAuthn settings (ADR-0022 A). RP = Relying Party.
    # `rp_id` должен matched domain'у браузера (origin check); `localhost`
    # для local dev, production выставляет `rehome.one`. Изменение RP_ID
    # инвалидирует все registered keys (security feature, не bug).
    webauthn_rp_id: str = Field(default="localhost", alias="WEBAUTHN_RP_ID")
    webauthn_rp_name: str = Field(default="reHome Vault", alias="WEBAUTHN_RP_NAME")
    # Origin для assertion validation. Comma-separated если multiple
    # (e.g. `https://rehome.one,https://app.rehome.one`).
    webauthn_origins: str = Field(
        default="http://localhost:3000",
        alias="WEBAUTHN_ORIGINS",
    )
    # `preferred` accept'ит auth UV если authenticator supports; не
    # требует — иначе users без biometric authenticator locked out.
    webauthn_user_verification: Literal["required", "preferred", "discouraged"] = Field(
        default="preferred",
        alias="WEBAUTHN_USER_VERIFICATION",
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def webauthn_origin_list(self) -> tuple[str, ...]:
        """Parsed origin list (comma-separated) для WebAuthn validation."""
        return tuple(o.strip() for o in self.webauthn_origins.split(",") if o.strip())


def get_settings() -> Settings:
    """Build a fresh Settings instance (reads env at call time).

    Намеренно не кэшируется: значения env могут меняться в тестах через
    `monkeypatch.setenv`, и каждое чтение `/version` отражает текущее
    окружение. Производительности это не вредит — endpoint вызывается редко.
    """
    return Settings()

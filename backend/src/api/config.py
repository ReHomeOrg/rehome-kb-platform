"""Application configuration loaded from environment variables.

См. README.md → раздел «Переменные окружения». Все значения имеют дефолты,
поэтому приложение запускается «из коробки» без `.env` (что нужно для CI и
для smoke-теста после `make run`).
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the kb-API gateway."""

    api_version: str = Field(default="1.0.0-alpha", alias="REHOME_API_VERSION")
    git_commit: str = Field(default="unknown", alias="GIT_COMMIT")
    build_date: str = Field(default="unknown", alias="BUILD_DATE")
    environment: str = Field(default="dev", alias="REHOME_ENV")

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        populate_by_name=True,
    )


def get_settings() -> Settings:
    """Build a fresh Settings instance (reads env at call time).

    Намеренно не кэшируется: значения env могут меняться в тестах через
    `monkeypatch.setenv`, и каждое чтение `/version` отражает текущее
    окружение. Производительности это не вредит — endpoint вызывается редко.
    """
    return Settings()

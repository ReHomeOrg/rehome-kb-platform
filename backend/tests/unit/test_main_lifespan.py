"""Lifespan tests для main.py: webhook worker start/stop + log_format=json branch.

Closes coverage gaps в main.py:43-50 (worker boot), 55-56 (worker stop),
78 (json log formatter install).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.api.config import Settings


@pytest.fixture
def patch_settings(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Override `get_settings()` returning controlled Settings."""
    overrides: dict[str, Any] = {}

    def _factory() -> Settings:
        defaults: dict[str, Any] = {"webhook_worker_enabled": False, "log_format": "text"}
        defaults.update(overrides)
        return Settings.model_validate(defaults)

    monkeypatch.setattr("src.api.main.get_settings", _factory)
    return overrides


@pytest.fixture
def fake_worker_class(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub WebhookDeliveryWorker — capture instances + assert start/stop."""
    instances: list[MagicMock] = []

    class _FakeWorker:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.started = False
            self.stopped = False
            instances.append(self)  # type: ignore[arg-type]

        def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr("src.api.main.WebhookDeliveryWorker", _FakeWorker)

    # mock get_engine — иначе lifespan создаст реальный async engine
    monkeypatch.setattr("src.api.main.get_engine", lambda: MagicMock())

    # Expose instances через MagicMock с attribute access
    holder = MagicMock()
    holder.instances = instances
    return holder


@pytest.mark.asyncio
async def test_lifespan_webhook_worker_enabled_starts_and_stops(
    patch_settings: dict[str, Any],
    fake_worker_class: MagicMock,
) -> None:
    """`webhook_worker_enabled=True` → worker boot'ится в lifespan, stop'ится
    при shutdown."""
    patch_settings["webhook_worker_enabled"] = True

    from src.api.main import lifespan

    fake_app = MagicMock()
    async with lifespan(fake_app):
        # Внутри context: worker должен быть start'нут.
        assert len(fake_worker_class.instances) == 1
        worker = fake_worker_class.instances[0]
        assert worker.started is True
        assert worker.stopped is False

    # После exit: worker должен быть stop'нут.
    assert fake_worker_class.instances[0].stopped is True


@pytest.mark.asyncio
async def test_lifespan_webhook_worker_disabled_no_op(
    patch_settings: dict[str, Any],
    fake_worker_class: MagicMock,
) -> None:
    """Default `webhook_worker_enabled=False` → worker не создаётся."""
    from src.api.main import lifespan

    fake_app = MagicMock()
    async with lifespan(fake_app):
        assert fake_worker_class.instances == []


def test_log_format_json_triggers_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """`LOG_FORMAT=json` → `install_json_log_formatter()` called.

    `src.api.main` уже импортирован к моменту запуска тестов с default
    `LOG_FORMAT=text` — в module-level выполнен ветка else. Чтобы
    проверить json-ветку, перезагружаем модуль с patch'ем.
    """
    import importlib

    install_called = MagicMock()
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setattr(
        "src.api.observability.install_json_log_formatter",
        install_called,
    )

    import src.api.main as main_module

    importlib.reload(main_module)
    # Restore default — последующие тесты не должны видеть стороннего
    # JSON formatter'а.
    monkeypatch.setenv("LOG_FORMAT", "text")
    importlib.reload(main_module)

    install_called.assert_called_once()

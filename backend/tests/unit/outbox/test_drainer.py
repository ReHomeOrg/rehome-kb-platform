"""Unit tests для OutboxDrainer (#356, ADR-0026 Slice 0)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.outbox import drainer as drainer_module
from src.api.outbox.drainer import OutboxDrainer, close_drainer, init_drainer
from src.api.outbox.models import OutboxRow


def _settings(enabled: bool = True, interval: float = 0.01, batch: int = 100) -> Any:
    s = MagicMock()
    s.outbox_drainer_enabled = enabled
    s.outbox_drainer_poll_interval_seconds = interval
    s.outbox_drainer_batch_size = batch
    return s


class _FakeSessionCtx:
    """Async ctx-manager yielding mock session с commit/rollback."""

    def __init__(self) -> None:
        self.session = MagicMock()
        self.session.commit = AsyncMock()
        self.session.execute = AsyncMock()
        self.session.add = MagicMock()

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


def _row(event_type: str = "article.published") -> OutboxRow:
    r = OutboxRow()
    r.id = uuid4()
    r.event_type = event_type
    r.payload = {"k": "v"}
    return r


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    """Singleton isolation между tests (ADR-0026 + #350 pattern)."""
    drainer_module._drainer_instance = None
    yield
    drainer_module._drainer_instance = None


# ---------------------------------------------------------------------------
# init_drainer / close_drainer


@pytest.mark.asyncio
async def test_init_disabled_returns_none() -> None:
    """`outbox_drainer_enabled=False` — no-op, drainer не start'ится."""
    factory = MagicMock()
    result = init_drainer(factory, _settings(enabled=False))
    assert result is None
    assert drainer_module._drainer_instance is None


@pytest.mark.asyncio
async def test_init_enabled_starts_drainer() -> None:
    factory = MagicMock(return_value=_FakeSessionCtx())
    result = init_drainer(factory, _settings(enabled=True))
    assert result is not None
    assert isinstance(result, OutboxDrainer)
    assert drainer_module._drainer_instance is result
    await close_drainer()


@pytest.mark.asyncio
async def test_init_idempotent() -> None:
    factory = MagicMock(return_value=_FakeSessionCtx())
    first = init_drainer(factory, _settings(enabled=True))
    second = init_drainer(factory, _settings(enabled=True))
    assert first is second
    await close_drainer()


@pytest.mark.asyncio
async def test_close_resets_singleton() -> None:
    factory = MagicMock(return_value=_FakeSessionCtx())
    init_drainer(factory, _settings(enabled=True))
    await close_drainer()
    assert drainer_module._drainer_instance is None


@pytest.mark.asyncio
async def test_close_noop_when_not_init() -> None:
    """`close_drainer` без prior init — graceful no-op."""
    await close_drainer()
    assert drainer_module._drainer_instance is None


# ---------------------------------------------------------------------------
# _drain_once: success / failure / empty


@pytest.mark.asyncio
async def test_drain_once_empty_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """No unflushed rows — drainer skips fan-out + commit."""
    ctx = _FakeSessionCtx()
    factory = MagicMock(return_value=ctx)
    drainer = OutboxDrainer(session_factory=factory, settings=_settings())

    fetch_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "src.api.outbox.drainer.OutboxRepository.fetch_unflushed",
        fetch_mock,
    )

    drained = await drainer._drain_once()
    assert drained == 0
    fetch_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_drain_once_fans_out_and_marks_flushed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each unflushed row → list_subscribers → delivery.enqueue per sub →
    mark_flushed."""
    ctx = _FakeSessionCtx()
    factory = MagicMock(return_value=ctx)
    drainer = OutboxDrainer(session_factory=factory, settings=_settings())

    row = _row("article.published")
    sub1 = MagicMock()
    sub1.id = uuid4()
    sub2 = MagicMock()
    sub2.id = uuid4()

    fetch_mock = AsyncMock(return_value=[row])
    list_subs_mock = AsyncMock(return_value=[sub1, sub2])
    enqueue_mock = AsyncMock()
    mark_mock = AsyncMock()
    monkeypatch.setattr(
        "src.api.outbox.drainer.OutboxRepository.fetch_unflushed",
        fetch_mock,
    )
    monkeypatch.setattr(
        "src.api.outbox.drainer.WebhookRepository.list_subscribers",
        list_subs_mock,
    )
    monkeypatch.setattr(
        "src.api.outbox.drainer.WebhookDeliveryRepository.enqueue",
        enqueue_mock,
    )
    monkeypatch.setattr(
        "src.api.outbox.drainer.OutboxRepository.mark_flushed",
        mark_mock,
    )

    drained = await drainer._drain_once()
    assert drained == 1
    # Fan-out на ОБА subscribers.
    assert enqueue_mock.await_count == 2
    mark_mock.assert_awaited_once_with(row.id)
    ctx.session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_drain_once_row_failure_bumps_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exception на одной row → record_failure, drainer продолжает с
    остальными (не падает)."""
    ctx = _FakeSessionCtx()
    factory = MagicMock(return_value=ctx)
    drainer = OutboxDrainer(session_factory=factory, settings=_settings())

    row_bad = _row("bad.event")
    row_good = _row("good.event")

    fetch_mock = AsyncMock(return_value=[row_bad, row_good])

    # list_subscribers raises на 'bad.event', succeeds на 'good.event'.
    async def _list_subs(self: Any, event_type: str) -> list[Any]:
        if event_type == "bad.event":
            raise RuntimeError("DB hiccup")
        return []

    monkeypatch.setattr(
        "src.api.outbox.drainer.OutboxRepository.fetch_unflushed",
        fetch_mock,
    )
    monkeypatch.setattr(
        "src.api.outbox.drainer.WebhookRepository.list_subscribers",
        _list_subs,
    )
    record_mock = AsyncMock()
    mark_mock = AsyncMock()
    monkeypatch.setattr(
        "src.api.outbox.drainer.OutboxRepository.record_failure",
        record_mock,
    )
    monkeypatch.setattr(
        "src.api.outbox.drainer.OutboxRepository.mark_flushed",
        mark_mock,
    )

    drained = await drainer._drain_once()
    # Only good row flushed.
    assert drained == 1
    record_mock.assert_awaited_once()
    # mark_flushed called только для good row.
    mark_mock.assert_awaited_once_with(row_good.id)


# ---------------------------------------------------------------------------
# start/stop lifecycle


@pytest.mark.asyncio
async def test_start_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Двойной start не создаёт second task."""
    factory = MagicMock(return_value=_FakeSessionCtx())
    drainer = OutboxDrainer(
        session_factory=factory,
        settings=_settings(interval=0.05),
    )
    monkeypatch.setattr(
        "src.api.outbox.drainer.OutboxRepository.fetch_unflushed",
        AsyncMock(return_value=[]),
    )
    drainer.start()
    first_task = drainer._task
    drainer.start()
    assert drainer._task is first_task
    await drainer.stop()


@pytest.mark.asyncio
async def test_loop_survives_iteration_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_unflushed raises → loop logs + продолжает (не падает)."""
    factory = MagicMock(return_value=_FakeSessionCtx())
    drainer = OutboxDrainer(
        session_factory=factory,
        settings=_settings(interval=0.02),
    )
    fetch_mock = AsyncMock(side_effect=[RuntimeError("oops"), []])
    monkeypatch.setattr(
        "src.api.outbox.drainer.OutboxRepository.fetch_unflushed",
        fetch_mock,
    )
    drainer.start()
    await asyncio.sleep(0.1)  # >= 2 iterations.
    await drainer.stop()
    assert fetch_mock.await_count >= 2

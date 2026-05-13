"""E5 webhooks end-to-end integration tests (#93).

Покрывают полный pipeline: register → trigger → outbox → worker → HTTP POST →
mark_delivered/failed/dead_letter. Запускаются с реальным Postgres + Keycloak
через docker compose (см. CI workflow `Integration (Keycloak)`).

Worker НЕ автостартует в uvicorn (env-flag default False). В этих тестах
мы создаём `WebhookDeliveryWorker` instance вручную и вызываем `_run_once()`
напрямую — это deterministically обрабатывает batch и возвращается. Это
лучше, чем `start()` + `asyncio.sleep()`, потому что тесты остаются быстрыми
и не flaky.
"""

import asyncio
import json
import os
import secrets
import threading
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.config import Settings
from src.api.webhooks.signing import verify_signature
from src.api.webhooks.worker import WebhookDeliveryWorker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb")
RAW_DSN = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


# ---------------------------------------------------------------------------
# Echo server — collects POST bodies + lets test control response status.


class _Receiver:
    """Single-instance HTTP echo server для verify webhook delivery."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.response_status: int = 200
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    def start(self) -> None:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — stdlib API
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                outer.received.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": body,
                    }
                )
                self.send_response(outer.response_status)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *_args: Any) -> None:
                # Silence default stderr logging in tests.
                pass

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def url(self) -> str:
        # `host.docker.internal` НЕ нужен — uvicorn запущен на host'е (см. CI).
        return f"http://127.0.0.1:{self.port}/hook"


@pytest.fixture
def receiver() -> Iterator[_Receiver]:
    r = _Receiver()
    r.start()
    try:
        yield r
    finally:
        r.stop()


# ---------------------------------------------------------------------------
# Worker fixture — instance pointing at the same DB as uvicorn.


@pytest.fixture
async def worker_instance() -> AsyncIterator[WebhookDeliveryWorker]:
    """Standalone worker для прямого вызова `_run_once()` в тестах.

    Использует отдельный engine — не пересекается с uvicorn'овским
    pool'ом (избегаем connection conflicts).
    """
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        WEBHOOK_WORKER_ENABLED=False,
        WEBHOOK_DELIVERY_TIMEOUT_SECONDS=5.0,
        WEBHOOK_MAX_ATTEMPTS=3,
        WEBHOOK_BACKOFF_BASE_SECONDS=1.0,
    )
    worker = WebhookDeliveryWorker(session_factory=session_factory, settings=settings)
    try:
        yield worker
    finally:
        await worker.stop()
        await engine.dispose()


# ---------------------------------------------------------------------------
# DB cleanup tracker.


@pytest.fixture
async def cleanup() -> AsyncIterator[dict[str, list[Any]]]:
    """Collect IDs/slugs созданных в тесте; DELETE в teardown.

    `webhook_deliveries` имеют CASCADE FK на webhooks, поэтому достаточно
    удалить webhooks. Articles удаляем отдельно (no FK).
    """
    tracker: dict[str, list[Any]] = {
        "webhook_ids": [],
        "article_slugs": [],
        "chat_session_ids": [],
    }
    yield tracker
    conn = await asyncpg.connect(RAW_DSN)
    try:
        for wid in tracker["webhook_ids"]:
            await conn.execute("DELETE FROM webhooks WHERE id = $1", wid)
        for slug in tracker["article_slugs"]:
            await conn.execute("DELETE FROM articles WHERE slug = $1", slug)
        for sid in tracker["chat_session_ids"]:
            await conn.execute("DELETE FROM chat_sessions WHERE id = $1", sid)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Helpers


async def _register_webhook_direct(
    receiver_url: str,
    events: list[str],
    *,
    client_id: str = "e2e-test",
) -> dict[str, Any]:
    """Bypass API SSRF check (loopback receiver) — insert webhook напрямую.

    SSRF-валидация URL покрыта unit'ом (`test_post_ssrf_blocks_internal_url`).
    Здесь integration-тест проверяет delivery pipeline, не registration —
    значит, корректно пропустить registration step.
    """
    secret = secrets.token_urlsafe(32)
    conn = await asyncpg.connect(RAW_DSN)
    try:
        row = await conn.fetchrow(
            "INSERT INTO webhooks (client_id, url, events, secret, description) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            client_id,
            receiver_url,
            events,
            secret,
            "e2e",
        )
        assert row is not None
        return {"id": str(row["id"]), "secret": secret}
    finally:
        await conn.close()


def _create_article(
    kb_client: httpx.Client,
    m2m_token: str,
    slug: str,
    status_value: str = "PUBLISHED",
) -> dict[str, Any]:
    resp = kb_client.post(
        "/api/v1/articles",
        json={
            "slug": slug,
            "title": f"Test {slug}",
            "body_markdown": "# body",
            "category": "guide",
            "audience": "tenant",
            "access_level": "PUBLIC",
            "status": status_value,
        },
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def _force_due_now(delivery_id: UUID) -> None:
    """Сдвинуть next_attempt_at в прошлое для retry-test'а без real sleep."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        await conn.execute(
            "UPDATE webhook_deliveries SET next_attempt_at = NOW() - INTERVAL '1 second' "
            "WHERE id = $1",
            delivery_id,
        )
    finally:
        await conn.close()


async def _fetch_delivery(delivery_id: UUID) -> dict[str, Any]:
    conn = await asyncpg.connect(RAW_DSN)
    try:
        row = await conn.fetchrow(
            "SELECT status, attempt_count, last_status_code, last_error "
            "FROM webhook_deliveries WHERE id = $1",
            delivery_id,
        )
        assert row is not None
        return dict(row)
    finally:
        await conn.close()


async def _delivery_id_for_webhook(webhook_id: UUID) -> UUID:
    """Find the (single) pending or processed delivery row created by trigger."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        row = await conn.fetchrow(
            "SELECT id FROM webhook_deliveries WHERE webhook_id = $1 "
            "ORDER BY created_at DESC LIMIT 1",
            webhook_id,
        )
        assert row is not None, "no delivery row enqueued"
        return UUID(str(row["id"]))
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 1. Happy path: publish article → worker delivers with HMAC.


@pytest.mark.integration
async def test_publish_article_delivers_webhook_with_hmac(
    kb_client: httpx.Client,
    m2m_token: str,
    receiver: _Receiver,
    worker_instance: WebhookDeliveryWorker,
    cleanup: dict[str, list[Any]],
) -> None:
    wh = await _register_webhook_direct(receiver.url, events=["article.published"])
    cleanup["webhook_ids"].append(UUID(wh["id"]))
    secret = wh["secret"]

    slug = f"e5e2e-pub-{uuid4().hex[:8]}"
    cleanup["article_slugs"].append(slug)
    _create_article(kb_client, m2m_token, slug, status_value="PUBLISHED")

    processed = await worker_instance._run_once()
    assert processed >= 1

    assert len(receiver.received) == 1
    req = receiver.received[0]
    assert req["headers"]["X-Rehome-Event"] == "article.published"
    sig = req["headers"]["X-Rehome-Signature"]
    assert sig.startswith("sha256=")
    assert verify_signature(secret, req["body"], sig)
    payload = json.loads(req["body"])
    assert payload["event"] == "article.published"
    assert payload["data"]["slug"] == slug

    # DB row finalized.
    delivery_id = await _delivery_id_for_webhook(UUID(wh["id"]))
    row = await _fetch_delivery(delivery_id)
    assert row["status"] == "delivered"
    assert row["last_status_code"] == 200


# ---------------------------------------------------------------------------
# 2. 5xx → attempt_count incremented, next_attempt_at scheduled.


@pytest.mark.integration
async def test_5xx_response_schedules_retry(
    kb_client: httpx.Client,
    m2m_token: str,
    receiver: _Receiver,
    worker_instance: WebhookDeliveryWorker,
    cleanup: dict[str, list[Any]],
) -> None:
    receiver.response_status = 503

    wh = await _register_webhook_direct(receiver.url, events=["article.published"])
    cleanup["webhook_ids"].append(UUID(wh["id"]))

    slug = f"e5e2e-5xx-{uuid4().hex[:8]}"
    cleanup["article_slugs"].append(slug)
    _create_article(kb_client, m2m_token, slug, status_value="PUBLISHED")

    await worker_instance._run_once()
    delivery_id = await _delivery_id_for_webhook(UUID(wh["id"]))
    row = await _fetch_delivery(delivery_id)
    assert row["status"] == "pending"
    assert row["attempt_count"] == 1
    assert row["last_status_code"] == 503
    assert "503" in (row["last_error"] or "")


# ---------------------------------------------------------------------------
# 3. Max attempts → dead_letter.


@pytest.mark.integration
async def test_max_attempts_marks_dead_letter(
    kb_client: httpx.Client,
    m2m_token: str,
    receiver: _Receiver,
    worker_instance: WebhookDeliveryWorker,
    cleanup: dict[str, list[Any]],
) -> None:
    receiver.response_status = 500

    wh = await _register_webhook_direct(receiver.url, events=["article.published"])
    cleanup["webhook_ids"].append(UUID(wh["id"]))

    slug = f"e5e2e-dead-{uuid4().hex[:8]}"
    cleanup["article_slugs"].append(slug)
    _create_article(kb_client, m2m_token, slug, status_value="PUBLISHED")

    delivery_id = await _delivery_id_for_webhook(UUID(wh["id"]))

    # MAX_ATTEMPTS=3 в worker_instance settings — 3 неуспешных run'а → dead_letter.
    for _ in range(3):
        await worker_instance._run_once()
        await _force_due_now(delivery_id)  # сдвигаем next_attempt_at в прошлое.

    row = await _fetch_delivery(delivery_id)
    assert row["status"] == "dead_letter"
    assert row["attempt_count"] == 3
    # Receiver получил 3 retry-попытки.
    assert len(receiver.received) == 3


# ---------------------------------------------------------------------------
# 4. SKIP LOCKED — concurrent claim_pending не возвращают пересекающихся rows.


@pytest.mark.integration
async def test_concurrent_claim_pending_no_overlap(
    kb_client: httpx.Client,
    m2m_token: str,
    receiver: _Receiver,
    cleanup: dict[str, list[Any]],
) -> None:
    """SELECT FOR UPDATE SKIP LOCKED safety — две concurrent сессии должны
    разделить pending deliveries без overlap'а."""
    wh = await _register_webhook_direct(receiver.url, events=["article.published"])
    cleanup["webhook_ids"].append(UUID(wh["id"]))

    # Enqueue 5 pending deliveries напрямую (без trigger'а — быстрее).
    conn = await asyncpg.connect(RAW_DSN)
    enqueued_ids: list[UUID] = []
    try:
        for _ in range(5):
            row = await conn.fetchrow(
                "INSERT INTO webhook_deliveries (webhook_id, event_type, payload) "
                "VALUES ($1, $2, $3::jsonb) RETURNING id",
                UUID(wh["id"]),
                "article.published",
                json.dumps({"slug": "x"}),
            )
            assert row is not None
            enqueued_ids.append(UUID(str(row["id"])))
    finally:
        await conn.close()

    from src.api.webhooks.delivery_repository import WebhookDeliveryRepository

    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _claim() -> set[UUID]:
        async with session_factory() as session:
            repo = WebhookDeliveryRepository(session)
            rows = await repo.claim_pending(limit=10)
            # Hold the lock for a short window so the parallel claim sees SKIP_LOCKED.
            await asyncio.sleep(0.3)
            return {r.id for r in rows}

    try:
        claim_a, claim_b = await asyncio.gather(_claim(), _claim())
    finally:
        await engine.dispose()

    # Зеркальное условие: union покрывает все enqueued; intersection пуста.
    assert claim_a.isdisjoint(claim_b)
    assert claim_a | claim_b == set(enqueued_ids)


# ---------------------------------------------------------------------------
# 5. chat.escalated end-to-end (separate trigger path).


@pytest.mark.integration
async def test_chat_escalated_delivers_webhook(
    kb_client: httpx.Client,
    m2m_token: str,
    receiver: _Receiver,
    worker_instance: WebhookDeliveryWorker,
    cleanup: dict[str, list[Any]],
) -> None:
    wh = await _register_webhook_direct(receiver.url, events=["chat.escalated"])
    cleanup["webhook_ids"].append(UUID(wh["id"]))
    secret = wh["secret"]

    # m2m JWT.sub — это service-account имя (НЕ UUID), поэтому
    # `extract_chat_owner` отдаёт anon flow: server возвращает
    # `X-Chat-Session-Token`, который мы должны слать обратно при escalate.
    sess_resp = kb_client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert sess_resp.status_code == 201, sess_resp.text
    session_id = sess_resp.json()["id"]
    session_token = sess_resp.headers["X-Chat-Session-Token"]
    cleanup["chat_session_ids"].append(UUID(session_id))

    esc_resp = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/escalate",
        json={"priority": "high"},
        headers={"X-Chat-Session-Token": session_token},
    )
    assert esc_resp.status_code == 201, esc_resp.text

    processed = await worker_instance._run_once()
    assert processed >= 1

    assert len(receiver.received) == 1
    req = receiver.received[0]
    assert req["headers"]["X-Rehome-Event"] == "chat.escalated"
    assert verify_signature(secret, req["body"], req["headers"]["X-Rehome-Signature"])
    payload = json.loads(req["body"])
    assert payload["event"] == "chat.escalated"
    assert payload["data"]["session_id"] == session_id
    assert payload["data"]["priority"] == "high"


# ---------------------------------------------------------------------------
# 6. Idempotent claim — повторный _run_once без новых rows возвращает 0.


@pytest.mark.integration
async def test_run_once_idempotent_after_delivery(
    kb_client: httpx.Client,
    m2m_token: str,
    receiver: _Receiver,
    worker_instance: WebhookDeliveryWorker,
    cleanup: dict[str, list[Any]],
) -> None:
    wh = await _register_webhook_direct(receiver.url, events=["article.published"])
    cleanup["webhook_ids"].append(UUID(wh["id"]))

    slug = f"e5e2e-idem-{uuid4().hex[:8]}"
    cleanup["article_slugs"].append(slug)
    _create_article(kb_client, m2m_token, slug, status_value="PUBLISHED")

    first = await worker_instance._run_once()
    assert first >= 1
    second = await worker_instance._run_once()
    assert second == 0
    assert len(receiver.received) == 1  # NOT re-delivered.

    # Quiet usage of datetime so import isn't unused on type-checker pass.
    assert isinstance(datetime.now(UTC), datetime)

"""Unit tests для admin analytics router (2026-05-28)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.articles.questions_repository import (
    ArticleQuestionRepository,
    get_article_question_repository,
)
from src.api.chat.unanswered_queries import (
    ChatUnansweredQueryRepository,
    get_chat_unanswered_query_repository,
)
from src.api.main import app
from src.api.search.query_log import (
    SearchQueryLogRepository,
    get_search_query_log_repository,
)


@pytest.fixture
def search_repo_mock() -> AsyncMock:
    mock = AsyncMock(spec=SearchQueryLogRepository)
    mock.find_top_queries = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def question_repo_mock() -> AsyncMock:
    mock = AsyncMock(spec=ArticleQuestionRepository)
    mock.count_by_article = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def unanswered_repo_mock() -> AsyncMock:
    mock = AsyncMock(spec=ChatUnansweredQueryRepository)
    mock.find_top_normalized = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def override_deps(
    search_repo_mock: AsyncMock,
    question_repo_mock: AsyncMock,
    unanswered_repo_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    app.dependency_overrides[get_search_query_log_repository] = lambda: search_repo_mock
    app.dependency_overrides[get_article_question_repository] = lambda: question_repo_mock
    app.dependency_overrides[get_chat_unanswered_query_repository] = lambda: unanswered_repo_mock
    yield {
        "search": search_repo_mock,
        "questions": question_repo_mock,
        "unanswered": unanswered_repo_mock,
    }
    app.dependency_overrides.pop(get_search_query_log_repository, None)
    app.dependency_overrides.pop(get_article_question_repository, None)
    app.dependency_overrides.pop(get_chat_unanswered_query_repository, None)


# ---------------------------------------------------------------------------
# /queries


def test_queries_requires_auth(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
) -> None:
    resp = client.get("/api/v1/admin/analytics/queries")
    assert resp.status_code == 401


def test_queries_403_for_non_staff_admin(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """tenant — без LEGAL → 403."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/queries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_queries_returns_top_queries_with_breakdown(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Repo returns 3 queries → response содержит data + window_hours.

    Each row: total + with_results + without_results breakdown.
    """
    override_deps["search"].find_top_queries.return_value = [
        ("сервисный сбор", 10, 8),  # 8 с answers, 2 — нет
        ("оплата", 5, 5),  # все answered
        ("кэдо", 3, 0),  # все unanswered = content gap
    ]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/queries?window_hours=24",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["window_hours"] == 24
    assert len(body["data"]) == 3
    assert body["data"][0]["query"] == "сервисный сбор"
    assert body["data"][0]["total"] == 10
    assert body["data"][0]["with_results"] == 8
    assert body["data"][0]["without_results"] == 2
    # «кэдо» — content gap.
    assert body["data"][2]["without_results"] == 3


def test_queries_window_clamp_to_max(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """window_hours > 720 (30 days) — 422 validation."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/queries?window_hours=10000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /article-questions


def test_article_questions_requires_auth(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
) -> None:
    resp = client.get("/api/v1/admin/analytics/article-questions")
    assert resp.status_code == 401


def test_article_questions_403_for_non_staff_admin(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/article-questions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_article_questions_returns_per_article_counts(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Articles c PENDING вопросами — sorted DESC by pending."""
    a1, a2 = uuid4(), uuid4()
    override_deps["questions"].count_by_article.return_value = [
        (a1, "slug-1", "Title 1", 3, 2, 0),  # 3 pending, 2 answered, 0 dismissed
        (a2, "slug-2", "Title 2", 1, 5, 1),  # 1 pending, 5 answered, 1 dismissed
    ]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/article-questions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["data"]) == 2
    first = body["data"][0]
    assert first["article_id"] == str(a1)
    assert first["slug"] == "slug-1"
    assert first["pending"] == 3
    assert first["answered"] == 2
    assert first["dismissed"] == 0
    assert first["total"] == 5  # 3+2+0
    second = body["data"][1]
    assert second["total"] == 7  # 1+5+1


def test_article_questions_empty_result_returns_empty_data(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["questions"].count_by_article.return_value = []
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/article-questions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ---------------------------------------------------------------------------
# /unanswered-queries


def test_unanswered_queries_requires_auth(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
) -> None:
    resp = client.get("/api/v1/admin/analytics/unanswered-queries")
    assert resp.status_code == 401


def test_unanswered_queries_403_for_non_staff_admin(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/unanswered-queries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_unanswered_queries_returns_trend_buckets(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Repo возвращает 2 bucket'а — response сохраняет порядок + поля."""
    now = datetime.now(UTC)
    first = now - timedelta(hours=20)
    last = now - timedelta(hours=1)
    override_deps["unanswered"].find_top_normalized.return_value = [
        ("страховой полис", 5, first, last),
        ("кэдо", 3, first, last),
    ]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/unanswered-queries?window_hours=24",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["window_hours"] == 24
    assert body["status"] == "NEW"
    assert len(body["data"]) == 2
    assert body["data"][0]["normalized_query"] == "страховой полис"
    assert body["data"][0]["count"] == 5
    assert "first_seen" in body["data"][0]
    assert "last_seen" in body["data"][0]


def test_unanswered_queries_default_status_filter_is_new(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Без status query param — repo вызывается с status_filter='NEW'."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/unanswered-queries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    call = override_deps["unanswered"].find_top_normalized.await_args
    assert call.kwargs["status_filter"] == "NEW"


def test_unanswered_queries_explicit_status_passes_through(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/unanswered-queries?status=DISMISSED",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    call = override_deps["unanswered"].find_top_normalized.await_args
    assert call.kwargs["status_filter"] == "DISMISSED"
    assert resp.json()["status"] == "DISMISSED"


def test_unanswered_queries_invalid_status_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/unanswered-queries?status=GARBAGE",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_unanswered_queries_window_clamp(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """window_hours > 720 → 422."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/unanswered-queries?window_hours=10000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_unanswered_queries_empty_result(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["unanswered"].find_top_normalized.return_value = []
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/analytics/unanswered-queries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []

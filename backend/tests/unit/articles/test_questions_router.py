"""Unit tests для Article Q&A router (ТЗ §2, 2026-05-28)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.articles.models import Article, ArticleQuestion
from src.api.articles.questions_repository import (
    ArticleQuestionRepository,
    get_article_question_repository,
)
from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.db import get_session
from src.api.main import app


def _make_article(slug: str = "test-article") -> Article:
    a = Article()
    a.id = uuid4()
    a.slug = slug
    a.title = "Test"
    a.body_markdown = "body"
    a.audience = "all"
    a.access_level = "PUBLIC"
    a.status = "PUBLISHED"
    a.language = "ru"
    a.category = "test"
    a.tags = []
    a.published_at = datetime.now(UTC)
    a.created_at = datetime.now(UTC)
    a.updated_at = datetime.now(UTC)
    return a


def _make_question(
    article_id: Any = None,
    status: str = "PENDING",
    body: str = "Test question",
) -> ArticleQuestion:
    q = ArticleQuestion()
    q.id = uuid4()
    q.article_id = article_id or uuid4()
    q.author_sub = "user-sub-1"
    q.body = body
    q.status = status
    q.created_at = datetime.now(UTC)
    q.updated_at = datetime.now(UTC)
    if status == "ANSWERED":
        q.answer_body = "Test answer"
        q.answerer_sub = "staff-sub"
        q.answered_at = datetime.now(UTC)
    return q


@pytest.fixture
def repo_mocks() -> dict[str, AsyncMock]:
    return {
        "create": AsyncMock(),
        "get_by_id": AsyncMock(return_value=None),
        "list_public_for_article": AsyncMock(return_value=[]),
        "list_admin": AsyncMock(return_value=([], 0)),
        "mark_answered": AsyncMock(return_value=None),
        "mark_dismissed": AsyncMock(return_value=None),
    }


@pytest.fixture
def article_repo_mocks() -> dict[str, AsyncMock]:
    return {"get_by_slug": AsyncMock(return_value=None)}


@pytest.fixture
def override_deps(
    repo_mocks: dict[str, AsyncMock],
    article_repo_mocks: dict[str, AsyncMock],
) -> Iterator[dict[str, Any]]:
    repo = ArticleQuestionRepository.__new__(ArticleQuestionRepository)
    for name, mock in repo_mocks.items():
        setattr(repo, name, mock)

    art_repo = ArticleRepository.__new__(ArticleRepository)
    for name, mock in article_repo_mocks.items():
        setattr(art_repo, name, mock)

    audit_record = AsyncMock()
    audit = AuditRepository.__new__(AuditRepository)
    audit.record = audit_record  # type: ignore[method-assign]

    async def _session() -> Any:
        s = MagicMock()
        s.commit = AsyncMock()
        s.rollback = AsyncMock()
        s.flush = AsyncMock()
        yield s

    app.dependency_overrides[get_article_question_repository] = lambda: repo
    app.dependency_overrides[get_article_repository] = lambda: art_repo
    app.dependency_overrides[get_audit_repository] = lambda: audit
    app.dependency_overrides[get_session] = _session

    yield {
        "repo": repo_mocks,
        "article_repo": article_repo_mocks,
        "audit_record": audit_record,
    }
    app.dependency_overrides.pop(get_article_question_repository, None)
    app.dependency_overrides.pop(get_article_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# Public endpoints


def test_list_public_questions_returns_only_answered(
    client: TestClient,
    override_deps: dict[str, Any],
) -> None:
    article = _make_article()
    override_deps["article_repo"]["get_by_slug"].return_value = article
    q1 = _make_question(article.id, status="ANSWERED", body="Q1")
    override_deps["repo"]["list_public_for_article"].return_value = [q1]

    resp = client.get(f"/api/v1/articles/{article.slug}/questions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["data"]) == 1
    # author_sub НЕ присутствует (privacy).
    assert "author_sub" not in body["data"][0]
    assert body["data"][0]["body"] == "Q1"


def test_list_public_questions_404_when_article_not_found(
    client: TestClient,
    override_deps: dict[str, Any],
) -> None:
    override_deps["article_repo"]["get_by_slug"].return_value = None
    resp = client.get("/api/v1/articles/missing-slug/questions")
    assert resp.status_code == 404


def test_submit_question_requires_auth(
    client: TestClient,
    override_deps: dict[str, Any],
) -> None:
    resp = client.post(
        "/api/v1/articles/some-slug/questions",
        json={"body": "Question?"},
    )
    assert resp.status_code == 401


def test_submit_question_creates_pending_and_audits(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    article = _make_article()
    override_deps["article_repo"]["get_by_slug"].return_value = article
    new_q = _make_question(article.id, body="My question?")
    override_deps["repo"]["create"].return_value = new_q

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/articles/{article.slug}/questions",
        json={"body": "My question?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    # Audit was recorded.
    override_deps["audit_record"].assert_awaited_once()
    audit_kwargs = override_deps["audit_record"].call_args.kwargs
    assert audit_kwargs["action"] == "article.question.submitted"
    # ФЗ-152: body НЕ в metadata.
    assert "body" not in audit_kwargs["metadata"]
    assert audit_kwargs["metadata"]["article_slug"] == article.slug


def test_submit_question_404_when_article_not_found(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["article_repo"]["get_by_slug"].return_value = None
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/articles/missing/questions",
        json={"body": "?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_submit_question_empty_body_returns_422(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/articles/x/questions",
        json={"body": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Admin moderation endpoints


def test_admin_list_requires_staff(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    """Tenant scope — 403."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/article-questions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_admin_list_returns_admin_view_with_total(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    q1 = _make_question(status="PENDING")
    q2 = _make_question(status="PENDING")
    override_deps["repo"]["list_admin"].return_value = ([q1, q2], 7)

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/article-questions?status=PENDING",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["total"] == 7
    # author_sub присутствует (admin view).
    assert body["data"][0]["author_sub"] == "user-sub-1"


def test_admin_answer_marks_answered_and_audits(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    pending = _make_question(status="PENDING")
    override_deps["repo"]["get_by_id"].return_value = pending
    answered = _make_question(status="ANSWERED")
    answered.id = pending.id  # same row
    override_deps["repo"]["mark_answered"].return_value = answered

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/article-questions/{pending.id}/answer",
        json={"answer_body": "Official answer here."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ANSWERED"

    audit_kwargs = override_deps["audit_record"].call_args.kwargs
    assert audit_kwargs["action"] == "article.question.answered"
    assert audit_kwargs["metadata"]["previous_status"] == "PENDING"
    # ФЗ-152: answer_body НЕ в metadata.
    assert "answer_body" not in audit_kwargs["metadata"]


def test_admin_answer_404_when_not_found(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["repo"]["get_by_id"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/article-questions/{uuid4()}/answer",
        json={"answer_body": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_admin_dismiss_marks_dismissed(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    pending = _make_question(status="PENDING")
    override_deps["repo"]["get_by_id"].return_value = pending
    dismissed = _make_question(status="DISMISSED")
    dismissed.id = pending.id
    override_deps["repo"]["mark_dismissed"].return_value = dismissed

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/article-questions/{pending.id}/dismiss",
        json={"reason": "off-topic"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    audit_kwargs = override_deps["audit_record"].call_args.kwargs
    assert audit_kwargs["action"] == "article.question.dismissed"
    # ФЗ-152: reason value НЕ в metadata, только presence flag.
    assert audit_kwargs["metadata"]["reason_provided"] is True
    assert "reason" not in audit_kwargs["metadata"]


def test_admin_dismiss_409_for_already_answered(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    answered = _make_question(status="ANSWERED")
    override_deps["repo"]["get_by_id"].return_value = answered

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/article-questions/{answered.id}/dismiss",
        json={"reason": "trying to unpublish"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    # repo.mark_dismissed НЕ был вызван — early return.
    override_deps["repo"]["mark_dismissed"].assert_not_called()


def test_admin_dismiss_404_when_not_found(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["repo"]["get_by_id"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/article-questions/{uuid4()}/dismiss",
        json={"reason": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_submit_question_body_too_long_returns_422(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    """Anti-DoS body cap (2000 chars)."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/articles/x/questions",
        json={"body": "x" * 2001},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_admin_answer_body_too_long_returns_422(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    """Answer cap (5000 chars)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/article-questions/{uuid4()}/answer",
        json={"answer_body": "x" * 5001},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

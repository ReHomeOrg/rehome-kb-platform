"""Unit tests для chat_unanswered_queries admin router (2026-05-29)."""

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
from src.api.chat.unanswered_queries import (
    ChatUnansweredQuery,
    ChatUnansweredQueryRepository,
    get_chat_unanswered_query_repository,
)
from src.api.db import get_session
from src.api.main import app


def _make_article(slug: str = "rent-contract") -> Article:
    a = Article()
    a.id = uuid4()
    a.slug = slug
    a.title = "Test article"
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


def _make_row(
    *,
    status: str = "NEW",
    query_masked: str = "как продлить договор",
) -> ChatUnansweredQuery:
    row = ChatUnansweredQuery()
    row.id = uuid4()
    row.query_masked = query_masked
    row.author_sub = "user-1"
    row.chat_session_id = uuid4()
    row.status = status
    row.attached_question_id = None
    row.attached_article_slug = None
    row.dismiss_reason = None
    row.created_at = datetime.now(UTC)
    row.attached_at = None
    row.updated_at = datetime.now(UTC)
    return row


def _make_question(article_id: Any, body: str = "как продлить договор") -> ArticleQuestion:
    q = ArticleQuestion()
    q.id = uuid4()
    q.article_id = article_id
    q.author_sub = "user-1"
    q.body = body
    q.status = "PENDING"
    q.created_at = datetime.now(UTC)
    q.updated_at = datetime.now(UTC)
    return q


@pytest.fixture
def override_deps() -> Iterator[dict[str, Any]]:
    unanswered_repo = ChatUnansweredQueryRepository.__new__(ChatUnansweredQueryRepository)
    unanswered_repo.get_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    unanswered_repo.list_admin = AsyncMock(return_value=([], 0))  # type: ignore[method-assign]
    unanswered_repo.mark_attached = AsyncMock(return_value=None)  # type: ignore[method-assign]
    unanswered_repo.mark_dismissed = AsyncMock(return_value=None)  # type: ignore[method-assign]

    article_repo = ArticleRepository.__new__(ArticleRepository)
    article_repo.get_by_slug = AsyncMock(return_value=None)  # type: ignore[method-assign]

    question_repo = ArticleQuestionRepository.__new__(ArticleQuestionRepository)
    question_repo.create = AsyncMock()  # type: ignore[method-assign]

    audit = AuditRepository.__new__(AuditRepository)
    audit.record = AsyncMock()  # type: ignore[method-assign]

    async def _session() -> Any:
        s = MagicMock()
        s.commit = AsyncMock()
        s.rollback = AsyncMock()
        s.flush = AsyncMock()
        yield s

    app.dependency_overrides[get_chat_unanswered_query_repository] = lambda: unanswered_repo
    app.dependency_overrides[get_article_repository] = lambda: article_repo
    app.dependency_overrides[get_article_question_repository] = lambda: question_repo
    app.dependency_overrides[get_audit_repository] = lambda: audit
    app.dependency_overrides[get_session] = _session

    yield {
        "unanswered_repo": unanswered_repo,
        "article_repo": article_repo,
        "question_repo": question_repo,
        "audit": audit,
    }
    app.dependency_overrides.pop(get_chat_unanswered_query_repository, None)
    app.dependency_overrides.pop(get_article_repository, None)
    app.dependency_overrides.pop(get_article_question_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# GET /


def test_list_requires_staff(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/chat-unanswered-queries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_list_returns_rows_with_total(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    rows = [_make_row(), _make_row(status="NEW")]
    override_deps["unanswered_repo"].list_admin.return_value = (rows, 5)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/chat-unanswered-queries?status=NEW",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["total"] == 5
    # Author sub присутствует (admin view), query_masked тоже.
    assert body["data"][0]["author_sub"] == "user-1"
    assert "как продлить договор" in body["data"][0]["query_masked"]


# ---------------------------------------------------------------------------
# POST /{id}/attach


def test_attach_creates_article_question_and_marks_attached(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    row = _make_row(status="NEW")
    article = _make_article("rent-contract")
    new_question = _make_question(article.id)
    attached_row = _make_row(status="ATTACHED")
    attached_row.id = row.id
    attached_row.attached_question_id = new_question.id
    attached_row.attached_article_slug = article.slug
    attached_row.attached_at = datetime.now(UTC)

    override_deps["unanswered_repo"].get_by_id.return_value = row
    override_deps["article_repo"].get_by_slug.return_value = article
    override_deps["question_repo"].create.return_value = new_question
    override_deps["unanswered_repo"].mark_attached.return_value = attached_row

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/chat-unanswered-queries/{row.id}/attach",
        json={"article_slug": article.slug},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["unanswered"]["status"] == "ATTACHED"
    assert body["unanswered"]["attached_question_id"] == str(new_question.id)
    assert body["question"]["id"] == str(new_question.id)
    assert body["question"]["status"] == "PENDING"

    # Article question создан с body = row.query_masked (no override).
    create_kwargs = override_deps["question_repo"].create.call_args.kwargs
    assert create_kwargs["body"] == row.query_masked
    # author_sub preserved — original chat user.
    assert create_kwargs["author_sub"] == row.author_sub

    # Audit captures article_slug + question_id, NO body.
    audit_kwargs = override_deps["audit"].record.call_args.kwargs
    assert audit_kwargs["action"] == "chat.unanswered.attached"
    assert audit_kwargs["metadata"]["article_slug"] == article.slug
    assert audit_kwargs["metadata"]["question_id"] == str(new_question.id)
    assert "body" not in audit_kwargs["metadata"]


def test_attach_with_override_question_body(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    """Staff может переформулировать query перед attach."""
    row = _make_row(status="NEW")
    article = _make_article()
    new_question = _make_question(article.id)
    override_deps["unanswered_repo"].get_by_id.return_value = row
    override_deps["article_repo"].get_by_slug.return_value = article
    override_deps["question_repo"].create.return_value = new_question
    override_deps["unanswered_repo"].mark_attached.return_value = _make_row(status="ATTACHED")

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/chat-unanswered-queries/{row.id}/attach",
        json={
            "article_slug": article.slug,
            "question_body": "Можно ли продлить договор аренды на год?",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    create_kwargs = override_deps["question_repo"].create.call_args.kwargs
    assert create_kwargs["body"] == "Можно ли продлить договор аренды на год?"


def test_attach_404_when_row_not_found(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["unanswered_repo"].get_by_id.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/chat-unanswered-queries/{uuid4()}/attach",
        json={"article_slug": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_attach_409_for_already_attached(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    attached_row = _make_row(status="ATTACHED")
    override_deps["unanswered_repo"].get_by_id.return_value = attached_row
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/chat-unanswered-queries/{attached_row.id}/attach",
        json={"article_slug": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    # article_repo / question_repo НЕ были вызваны.
    override_deps["article_repo"].get_by_slug.assert_not_called()
    override_deps["question_repo"].create.assert_not_called()


def test_attach_404_when_article_slug_not_found(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    row = _make_row(status="NEW")
    override_deps["unanswered_repo"].get_by_id.return_value = row
    override_deps["article_repo"].get_by_slug.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/chat-unanswered-queries/{row.id}/attach",
        json={"article_slug": "missing"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    # question_repo create НЕ был вызван — early return.
    override_deps["question_repo"].create.assert_not_called()


# ---------------------------------------------------------------------------
# POST /{id}/dismiss


def test_dismiss_marks_dismissed_and_audits(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    row = _make_row(status="NEW")
    dismissed = _make_row(status="DISMISSED")
    dismissed.id = row.id
    dismissed.dismiss_reason = "out of scope"
    override_deps["unanswered_repo"].get_by_id.return_value = row
    override_deps["unanswered_repo"].mark_dismissed.return_value = dismissed

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/chat-unanswered-queries/{row.id}/dismiss",
        json={"reason": "out of scope"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "DISMISSED"
    audit_kwargs = override_deps["audit"].record.call_args.kwargs
    assert audit_kwargs["action"] == "chat.unanswered.dismissed"
    # ФЗ-152: reason value НЕ в metadata, только presence flag.
    assert audit_kwargs["metadata"]["reason_provided"] is True
    assert "reason" not in audit_kwargs["metadata"]


def test_dismiss_409_for_attached_row(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    attached = _make_row(status="ATTACHED")
    override_deps["unanswered_repo"].get_by_id.return_value = attached
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/chat-unanswered-queries/{attached.id}/dismiss",
        json={"reason": "late"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    # repo.mark_dismissed НЕ был вызван — early return.
    override_deps["unanswered_repo"].mark_dismissed.assert_not_called()


def test_dismiss_404_when_not_found(
    client: TestClient,
    override_deps: dict[str, Any],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["unanswered_repo"].get_by_id.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/admin/chat-unanswered-queries/{uuid4()}/dismiss",
        json={"reason": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404

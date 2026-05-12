"""Unit-тесты для `/api/v1/documents/*` router (E2.8 #56).

Покрывает:
- list: 200, default access_levels, фильтры, cursor/limit валидация.
- detail: 200 + 404 mask.
- download: 501.
- ADR-0003: scope-aware confidentiality via Depends override.
- related_entity regex validation.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.documents.models import Document
from src.api.documents.repository import DocumentRepository, get_document_repository
from src.api.main import app


def _doc(
    confidentiality: str = "PUBLIC",
    status: str = "ACTIVE",
    category: str = "A",
) -> Document:
    d = Document()
    d.id = uuid4()
    d.title = f"Doc {category}"
    d.category = category
    d.version = "1.0"
    d.effective_from = None
    d.effective_to = None
    d.status = status
    d.counterparty = None
    d.confidentiality = confidentiality
    d.related_entity = None
    d.files = []
    d.signed_by = []
    d.audit_log = []
    d.created_at = datetime(2026, 5, 12, tzinfo=UTC)
    d.updated_at = datetime(2026, 5, 12, tzinfo=UTC)
    return d


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=([], False))


@pytest.fixture
def get_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def override_repo(
    list_mock: AsyncMock, get_mock: AsyncMock
) -> Iterator[tuple[AsyncMock, AsyncMock]]:
    repo = DocumentRepository.__new__(DocumentRepository)
    repo.list_filtered = list_mock  # type: ignore[method-assign]
    repo.get_by_id = get_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_document_repository] = lambda: repo
    yield list_mock, get_mock
    app.dependency_overrides.pop(get_document_repository, None)


# ---------------------------------------------------------------------------
# GET /documents (list)


def test_list_returns_200_with_data_and_pagination(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    list_mock, _ = override_repo
    list_mock.return_value = ([_doc()], False)
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "pagination" in body
    assert len(body["data"]) == 1
    # signed_by / audit_log НЕ должны быть в list response (только в detail)
    assert "signed_by" not in body["data"][0]
    assert "audit_log" not in body["data"][0]


def test_list_guest_uses_public_only_confidentiality(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    """ADR-0003: guest → confidentiality={'PUBLIC'}."""
    list_mock, _ = override_repo
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    allowed: frozenset[str] = list_mock.call_args.args[0]
    assert allowed == frozenset({"PUBLIC"})


def test_list_jwt_tenant_widens_confidentiality(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    list_mock, _ = override_repo
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    allowed: frozenset[str] = list_mock.call_args.args[0]
    assert "PUBLIC" in allowed
    assert "INTERNAL" in allowed


def test_list_invalid_jwt_returns_401(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get(
        "/api/v1/documents",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


def test_list_category_filter_passed_to_repo(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    list_mock, _ = override_repo
    client.get("/api/v1/documents", params={"category": "B"})
    assert list_mock.call_args.kwargs["category"] == "B"


def test_list_invalid_category_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/documents", params={"category": "Z"})
    assert resp.status_code == 422


def test_list_invalid_status_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/documents", params={"status": "BAD"})
    assert resp.status_code == 422


def test_list_invalid_related_entity_regex_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    """Запретные символы в related_entity → 422."""
    resp = client.get("/api/v1/documents", params={"related_entity": "bad spaces here"})
    assert resp.status_code == 422


def test_list_valid_related_entity_passed_to_repo(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    list_mock, _ = override_repo
    client.get("/api/v1/documents", params={"related_entity": "user:abc-123"})
    assert list_mock.call_args.kwargs["related_entity"] == "user:abc-123"


def test_list_limit_above_max_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/documents", params={"limit": 101})
    assert resp.status_code == 422


def test_list_limit_zero_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/documents", params={"limit": 0})
    assert resp.status_code == 422


def test_list_invalid_cursor_returns_400(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/documents", params={"cursor": "!!!"})
    assert resp.status_code == 400


def test_list_has_more_sets_cursor_next(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    list_mock, _ = override_repo
    d = _doc()
    list_mock.return_value = ([d], True)
    resp = client.get("/api/v1/documents")
    body = resp.json()
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["cursor_next"] is not None


# ---------------------------------------------------------------------------
# GET /documents/{id}


def test_detail_returns_200_with_signed_by_and_audit_log(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    _, get_mock = override_repo
    d = _doc()
    d.signed_by = [
        {
            "role": "tenant",
            "name": "Иван Иванов",
            "date": "2026-05-12T00:00:00Z",
            "method": "sms_otp",
        }
    ]
    d.audit_log = [{"actor": "sub-1", "action": "created", "ts": "2026-05-12T00:00:00Z"}]
    get_mock.return_value = d
    resp = client.get(f"/api/v1/documents/{d.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert "signed_by" in body
    assert "audit_log" in body
    assert len(body["signed_by"]) == 1
    assert len(body["audit_log"]) == 1


def test_detail_returns_404_when_repo_returns_none(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    """ADR-0003 404-mask: scope не видит → 404 (не 403)."""
    _, get_mock = override_repo
    get_mock.return_value = None
    resp = client.get(f"/api/v1/documents/{uuid4()}")
    assert resp.status_code == 404


def test_detail_invalid_uuid_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/documents/not-a-uuid")
    assert resp.status_code == 422


def test_detail_guest_uses_public_only_confidentiality(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    _, get_mock = override_repo
    get_mock.return_value = None
    client.get(f"/api/v1/documents/{uuid4()}")
    allowed: frozenset[str] = get_mock.call_args.args[1]
    assert allowed == frozenset({"PUBLIC"})


# ---------------------------------------------------------------------------
# GET /documents/{id}/files/{format} → 501


def test_download_returns_501_not_implemented(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    """Download endpoint deferred (architect approved deviation)."""
    resp = client.get(f"/api/v1/documents/{uuid4()}/files/pdf")
    assert resp.status_code == 501
    body = resp.json()
    assert "not yet implemented" in body["detail"].lower()


def test_download_invalid_format_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    """Path-param `format` ∈ {docx, pdf, html}."""
    resp = client.get(f"/api/v1/documents/{uuid4()}/files/zip")
    assert resp.status_code == 422

"""Unit tests для audit-log search endpoint (#163)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.models import AuditLog
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.main import app


def _make_record(**over: Any) -> AuditLog:
    r = AuditLog()
    r.id = uuid4()
    r.actor_sub = "user-123"
    r.action = "articles.created"
    r.resource_type = "article"
    r.resource_id = "test-slug"
    r.audit_metadata = {"access_level": "PUBLIC"}
    r.created_at = datetime.now(UTC)
    for k, v in over.items():
        setattr(r, k, v)
    return r


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def override_audit_repo(list_mock: AsyncMock) -> Iterator[AsyncMock]:
    repo = AuditRepository.__new__(AuditRepository)
    # `record` нужен для autouse no-op fixture совместимости.
    repo.record = AsyncMock(return_value=None)  # type: ignore[method-assign]
    repo.list_records = list_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_audit_repository] = lambda: repo
    yield list_mock
    app.dependency_overrides.pop(get_audit_repository, None)


# ---------------------------------------------------------------------------
# auth boundary


def test_audit_requires_auth(client: TestClient, override_audit_repo: AsyncMock) -> None:
    resp = client.get("/api/v1/audit-log")
    assert resp.status_code == 401


def test_audit_tenant_403(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Tenant не имеет LEGAL access → 403."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_audit_staff_support_403(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_support имеет STAFF но НЕ LEGAL — 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_audit_staff_admin_has_access(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_admin даёт LEGAL access — 200."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# filters + pagination


def test_audit_returns_data_with_pagination_meta(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    list_mock.return_value = [_make_record(), _make_record(action="articles.updated")]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["pagination"] == {"limit": 50, "offset": 0, "count": 2}
    # `metadata` сериализуется (alias from audit_metadata).
    assert body["data"][0]["metadata"] == {"access_level": "PUBLIC"}


def test_audit_filters_passed_to_repo(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log"
        "?actor_sub=user-123"
        "&resource_type=article"
        "&resource_id=test-slug"
        "&action=articles.created"
        "&limit=10&offset=20",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    assert kwargs["actor_sub"] == "user-123"
    assert kwargs["resource_type"] == "article"
    assert kwargs["resource_id"] == "test-slug"
    assert kwargs["action"] == "articles.created"
    assert kwargs["limit"] == 10
    assert kwargs["offset"] == 20


def test_audit_date_filters(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log?since=2026-01-01T00:00:00Z&until=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    assert kwargs["since"] is not None
    assert kwargs["until"] is not None


def test_audit_q_filter_passed_to_repo(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Cube FF (#183) — `q` substring search метадаты."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log?q=article-foo",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_mock.call_args.kwargs["q"] == "article-foo"


def test_audit_q_default_none(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get("/api/v1/audit-log", headers={"Authorization": f"Bearer {token}"})
    assert list_mock.call_args.kwargs["q"] is None


def test_audit_q_too_long_returns_422(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """`q` clamp на 200 chars — anti-DoS на long ILIKE pattern."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/audit-log?q={'x' * 201}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_csv_export_q_passthrough(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """`q` also wired в CSV endpoint."""
    list_mock.return_value = []
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log/export.csv?q=needle",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_mock.call_args.kwargs["q"] == "needle"


def test_audit_invalid_limit_returns_422(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log?limit=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    resp = client.get(
        "/api/v1/audit-log?limit=201",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_audit_invalid_date_returns_422(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log?since=not-a-date",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_audit_no_filters_returns_recent_50(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    # Default limit=50, offset=0, остальные filters — None.
    assert kwargs["limit"] == 50
    assert kwargs["offset"] == 0
    assert kwargs["actor_sub"] is None
    assert kwargs["resource_type"] is None


# ---------------------------------------------------------------------------
# CSV export (#172)


def test_csv_export_requires_legal(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """tenant scope → 403 (no LEGAL)."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_csv_export_empty_returns_header_only(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Empty results → CSV с header row только (+ BOM)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.text
    # UTF-8 BOM prefix.
    assert body.startswith("﻿")
    lines = body.strip().split("\n")
    assert len(lines) == 1  # header only
    assert "created_at" in lines[0]
    assert "actor_sub" in lines[0]


def test_csv_export_serializes_rows(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    list_mock.return_value = [
        _make_record(action="articles.created", resource_id="my-slug"),
        _make_record(
            action="articles.updated",
            resource_id="x",
            audit_metadata={"changed": ["title", "body"]},
        ),
    ]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.text
    assert "articles.created" in body
    assert "articles.updated" in body
    assert "my-slug" in body
    # Metadata serialized as single-line JSON (CSV escapes " → "").
    assert '{""changed"":[""title"",""body""]}' in body


def test_csv_export_filename_includes_timestamp(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    cd = resp.headers["content-disposition"]
    assert 'filename="audit_log_' in cd
    assert ".csv" in cd


def test_csv_export_uses_max_limit(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Export endpoint passes CSV_EXPORT_MAX_ROWS limit (anti-DoS)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log/export.csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    assert kwargs["limit"] == 10_000
    assert kwargs["offset"] == 0


def test_csv_export_filter_passthrough(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log/export.csv?actor_sub=u1&resource_type=article",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    assert kwargs["actor_sub"] == "u1"
    assert kwargs["resource_type"] == "article"


# ---------------------------------------------------------------------------
# JSONL export (#352)


def test_jsonl_export_requires_legal(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """tenant scope → 403 (no LEGAL)."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.jsonl",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_jsonl_export_returns_ndjson_content_type(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.jsonl",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in resp.headers["content-disposition"]
    assert ".jsonl" in resp.headers["content-disposition"]


def test_jsonl_export_no_bom(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """В отличие от CSV — без UTF-8 BOM (programmatic consumers)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.jsonl",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert not resp.content.startswith(b"\xef\xbb\xbf")


def test_jsonl_export_each_line_is_valid_json(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """JSONL invariant: каждая строка — parseable JSON object."""
    import json as _json

    list_mock.return_value = [
        _make_record(action="articles.created", resource_id="slug-a"),
        _make_record(
            action="articles.updated",
            resource_id="slug-b",
            audit_metadata={"changed": ["title"]},
        ),
    ]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.jsonl",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    lines = [line for line in resp.text.splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        obj = _json.loads(line)
        assert isinstance(obj, dict)
        assert {"id", "ts", "actor_sub", "action", "resource_type", "metadata"} <= obj.keys()
    # Embedded metadata — not stringified.
    parsed = [_json.loads(line) for line in lines]
    by_action = {p["action"]: p for p in parsed}
    assert by_action["articles.updated"]["metadata"] == {"changed": ["title"]}


def test_jsonl_export_empty_result_returns_empty_body(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Empty filter result → 200 + empty body (no header row, unlike CSV)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log/export.jsonl",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.text == ""


def test_jsonl_export_uses_max_limit(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Same anti-DoS hard cap что CSV."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log/export.jsonl",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    assert kwargs["limit"] == 10_000
    assert kwargs["offset"] == 0


def test_jsonl_export_filter_passthrough(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Same filter params что CSV."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log/export.jsonl?actor_sub=u1&resource_type=article",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    assert kwargs["actor_sub"] == "u1"
    assert kwargs["resource_type"] == "article"


@pytest.mark.asyncio
async def test_repository_list_records_applies_filters() -> None:
    """Repository SQL inspection — verify фильтры попадают в bind params."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = AuditRepository(session)
    await repo.list_records(
        actor_sub="user-x",
        resource_type="article",
        action="articles.created",
        limit=10,
    )
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert "user-x" in flat
    assert "article" in flat
    assert "articles.created" in flat


@pytest.mark.asyncio
async def test_repository_q_filter_compiles_with_ilike_wildcards() -> None:
    """Cube SS (#196): q substring → ILIKE с %wrapping% над cast(metadata::text).

    Регрессионный guard для #181 FTS — если кто-то заменит ILIKE на == или
    забудет процент-wrap, тест провалится.
    """
    from unittest.mock import MagicMock

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = AuditRepository(session)
    await repo.list_records(q="article-foo", limit=10)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = list(compiled.params.values())
    # ILIKE pattern wrapped percentами для substring match'а.
    assert "%article-foo%" in flat


@pytest.mark.asyncio
async def test_repository_empty_q_skipped() -> None:
    """Empty string / None для q НЕ должны добавлять WHERE clause."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = AuditRepository(session)
    # Пустая строка falsy — не должна попасть в bind params.
    await repo.list_records(q="", limit=10)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    sql_text = str(compiled)
    # Нет ILIKE в скомпилированном SQL.
    assert "ILIKE" not in sql_text.upper() or "%%" not in str(compiled.params.values())


@pytest.mark.asyncio
async def test_repository_resource_id_filter_applied() -> None:
    """resource_id фильтр оборачивается в WHERE clause (line 101)."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = AuditRepository(session)
    await repo.list_records(resource_id="doc-123", limit=10)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert "doc-123" in flat


@pytest.mark.asyncio
async def test_repository_since_filter_applied() -> None:
    """since (datetime lower bound) → WHERE created_at >= :since (line 105)."""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = AuditRepository(session)
    since = datetime(2026, 5, 1, tzinfo=UTC)
    await repo.list_records(since=since, limit=10)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert since in flat


@pytest.mark.asyncio
async def test_repository_until_filter_applied() -> None:
    """until (datetime upper bound) → WHERE created_at < :until (line 107)."""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = AuditRepository(session)
    until = datetime(2026, 5, 31, tzinfo=UTC)
    await repo.list_records(until=until, limit=10)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert until in flat


def test_get_audit_repository_factory_returns_repo_with_session() -> None:
    """`get_audit_repository(session)` → AuditRepository(session) wrapper."""
    from unittest.mock import MagicMock

    from src.api.audit.repository import get_audit_repository

    fake_session = MagicMock()
    repo = get_audit_repository(fake_session)
    assert isinstance(repo, AuditRepository)
    assert repo._session is fake_session


# ---------------------------------------------------------------------------
# list_records_keyset (#343)


def _stub_session(rows: list[object]) -> Any:
    from unittest.mock import MagicMock

    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_list_records_keyset_returns_tuple_no_overshoot() -> None:
    """Repo возвращает <limit rows → has_more=False."""
    session = _stub_session([])
    repo = AuditRepository(session)
    rows, has_more = await repo.list_records_keyset(limit=10)
    assert rows == []
    assert has_more is False


@pytest.mark.asyncio
async def test_list_records_keyset_detects_overshoot() -> None:
    """limit=2 + DB returns 3 (limit+1) → rows[:2], has_more=True."""
    fake_rows = [object(), object(), object()]
    session = _stub_session(fake_rows)
    repo = AuditRepository(session)
    rows, has_more = await repo.list_records_keyset(limit=2)
    assert len(rows) == 2
    assert has_more is True


@pytest.mark.asyncio
async def test_list_records_keyset_sql_orders_desc_with_id_tiebreaker() -> None:
    """ORDER BY created_at DESC, id DESC — обязательно для keyset стабильности."""
    session = _stub_session([])
    repo = AuditRepository(session)
    await repo.list_records_keyset(limit=10)
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile()).lower()
    assert "order by audit_log.created_at desc, audit_log.id desc" in sql


@pytest.mark.asyncio
async def test_list_records_keyset_cursor_applies_where_predicate() -> None:
    """Cursor `(dt, uuid)` → WHERE (created_at < :dt OR (created_at = :dt AND id < :uuid))."""
    from datetime import UTC, datetime
    from uuid import uuid4

    session = _stub_session([])
    repo = AuditRepository(session)
    cursor_dt = datetime(2026, 5, 1, tzinfo=UTC)
    cursor_id = uuid4()
    await repo.list_records_keyset(cursor=(cursor_dt, cursor_id), limit=10)
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert cursor_dt in flat
    assert cursor_id in flat
    sql = str(compiled).lower()
    # OR keyset condition присутствует.
    assert "created_at <" in sql or "audit_log.created_at <" in sql


@pytest.mark.asyncio
async def test_list_records_keyset_filters_combine_with_cursor() -> None:
    """actor_sub + cursor → оба WHERE предиката применяются (combined AND)."""
    from datetime import UTC, datetime
    from uuid import uuid4

    session = _stub_session([])
    repo = AuditRepository(session)
    await repo.list_records_keyset(
        actor_sub="user-x",
        cursor=(datetime(2026, 5, 1, tzinfo=UTC), uuid4()),
        limit=10,
    )
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat = list(compiled.params.values())
    assert "user-x" in flat

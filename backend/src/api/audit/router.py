"""FastAPI router для `/api/v1/audit-log` (#163, #172, JSONL #352).

Compliance endpoints — ФЗ-152 Subject Access Request, forensic
review, admin "что сделал user X". STAFF / LEGAL access tier.

Audit log immutable — нет write endpoints (records создаются через
`AuditRepository.record` из других router'ов, не через эту surface).

Endpoints:
- `GET /api/v1/audit-log` — JSON paginated search
- `GET /api/v1/audit-log/export.csv` — CSV download (full filtered
  result, до 10000 rows hard cap для anti-DoS)
- `GET /api/v1/audit-log/export.jsonl` — JSONL (newline-delimited
  JSON) для grep-able programmatic ingest (admin task export
  format=json wires сюда).
"""

import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.audit.schemas import AuditListResponse, AuditRecordView
from src.api.auth.dependency import require_access_level, require_authenticated
from src.api.auth.scope import AccessLevel

# Hard cap для CSV/JSONL export — anti-DoS. 10k rows × ~500 bytes = ~5 MB,
# acceptable для one-shot download. Дальнейшие compliance dumps —
# через DB backup / pg_dump (operational, не API surface).
EXPORT_MAX_ROWS = 10_000

router = APIRouter(prefix="/audit-log", tags=["Audit"])


@router.get(
    "",
    response_model=AuditListResponse,
    response_model_by_alias=False,
    summary="Search audit log (STAFF / LEGAL)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        422: {"description": "Невалидный параметр (date format etc.)"},
    },
)
async def search_audit_log(
    actor_sub: str | None = Query(default=None, max_length=200),
    resource_type: str | None = Query(default=None, max_length=32),
    resource_id: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=64),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    q: str | None = Query(
        default=None,
        max_length=200,
        description="Substring match over metadata JSONB (#183, forensic discovery)",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _claims: dict[str, Any] = Depends(require_authenticated),
    # LEGAL — типичный compliance tier (юрист аудитует ФЗ-152).
    # STAFF — admin / поддержка. Любого из них достаточно.
    _legal_required: None = Depends(require_access_level(AccessLevel.LEGAL)),
    repo: AuditRepository = Depends(get_audit_repository),
) -> AuditListResponse:
    """`GET /api/v1/audit-log` — filtered search с offset pagination.

    Все фильтры optional + combined AND. Defaults — last 50 records DESC.

    Access: LEGAL tier обязателен (юрист / staff_admin / director).
    Anonymous → 401; tenant / landlord / staff_support → 403.

    Pagination — offset/limit (не cursor): audit log low-volume read,
    admin UI с jump-to-page нужнее чем consistent ordering при concurrent
    writes (audit append-only, нет risk'а tombstones).
    """
    rows = await repo.list_records(
        actor_sub=actor_sub,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        since=since,
        until=until,
        q=q,
        limit=limit,
        offset=offset,
    )
    return AuditListResponse(
        data=[AuditRecordView.model_validate(r) for r in rows],
        pagination={"limit": limit, "offset": offset, "count": len(rows)},
    )


@router.get(
    "/export.csv",
    summary="Export audit log as CSV (#172, LEGAL access)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        422: {"description": "Невалидный параметр"},
    },
)
async def export_audit_log_csv(
    actor_sub: str | None = Query(default=None, max_length=200),
    resource_type: str | None = Query(default=None, max_length=32),
    resource_id: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=64),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    _claims: dict[str, Any] = Depends(require_authenticated),
    _legal_required: None = Depends(require_access_level(AccessLevel.LEGAL)),
    repo: AuditRepository = Depends(get_audit_repository),
) -> StreamingResponse:
    """CSV download of filtered audit records.

    Same фильтры что и JSON endpoint. Hard cap `EXPORT_MAX_ROWS`
    (10000) для anti-DoS — caller должен narrow filters для дальнейших
    chunks (или использовать DB backup).

    Columns: `created_at,actor_sub,action,resource_type,resource_id,
    metadata_json`. Metadata serialized как single-line JSON для
    spreadsheet-safe handling.

    Content-Disposition `attachment` triggers browser download.
    Encoding: UTF-8 с BOM (Excel-compatible на Windows).
    """
    rows = await repo.list_records(
        actor_sub=actor_sub,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        since=since,
        until=until,
        q=q,
        limit=EXPORT_MAX_ROWS,
        offset=0,
    )

    buf = io.StringIO()
    # UTF-8 BOM для Excel — без BOM Excel decode'ит cyrillic как Cp1251.
    buf.write("﻿")
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(
        ["created_at", "actor_sub", "action", "resource_type", "resource_id", "metadata"]
    )
    for r in rows:
        writer.writerow(
            [
                r.created_at.isoformat(),
                r.actor_sub,
                r.action,
                r.resource_type,
                r.resource_id or "",
                json.dumps(r.audit_metadata, ensure_ascii=False, separators=(",", ":")),
            ]
        )

    filename = f"audit_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/export.jsonl",
    summary="Export audit log as JSONL (#352, LEGAL access)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        422: {"description": "Невалидный параметр"},
    },
)
async def export_audit_log_jsonl(
    actor_sub: str | None = Query(default=None, max_length=200),
    resource_type: str | None = Query(default=None, max_length=32),
    resource_id: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=64),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    _claims: dict[str, Any] = Depends(require_authenticated),
    _legal_required: None = Depends(require_access_level(AccessLevel.LEGAL)),
    repo: AuditRepository = Depends(get_audit_repository),
) -> StreamingResponse:
    """JSONL (newline-delimited JSON) download — same filters что CSV.

    Каждый row — отдельный JSON object на собственной строке. Это
    formatting choice: parseable line-by-line (jq, grep, streaming
    ingest), без обёртки в single huge JSON array (который требует
    весь буфер в memory у consumer'а).

    Schema per line: `{id, ts, actor_sub, action, resource_type,
    resource_id, metadata}`. `metadata` — embedded JSONB (не stringified).

    Hard cap `EXPORT_MAX_ROWS` (10000) — same anti-DoS rationale.
    UTF-8 БЕЗ BOM (consumers programmatic, Excel-compat не нужен).
    """
    rows = await repo.list_records(
        actor_sub=actor_sub,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        since=since,
        until=until,
        q=q,
        limit=EXPORT_MAX_ROWS,
        offset=0,
    )

    buf = io.StringIO()
    for r in rows:
        line = {
            "id": str(r.id),
            "ts": r.created_at.isoformat(),
            "actor_sub": r.actor_sub,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "metadata": r.audit_metadata,
        }
        buf.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")))
        buf.write("\n")

    filename = f"audit_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )

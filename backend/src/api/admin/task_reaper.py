"""Reap orphaned admin_tasks (#268, ADR-0020 B).

Called on lifespan startup. Tasks in PENDING/RUNNING older than
`STALE_THRESHOLD` (15 min default) — marked FAILED with reaper marker.

Rationale: asyncio.create_task tasks умирают on process restart. Без
reaper'а stale RUNNING rows remain forever; admin UI auto-polling
показывает stale status. ADR-0020 §«Crash recovery test plan».

Threshold = 15 min default — больше типичной reindex execution (50s
на 1000 articles) но меньше human-noticeable lag.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.api.admin.tasks_models import AdminTask

logger = logging.getLogger(__name__)

# 15 min — tunable если operational learning показывает что some task
# types regularly take longer (e.g. eval_run с real LLM).
STALE_THRESHOLD = timedelta(minutes=15)


async def reap_stale_tasks(
    session_factory: async_sessionmaker[Any],
    *,
    threshold: timedelta = STALE_THRESHOLD,
    now: datetime | None = None,
) -> int:
    """Mark PENDING/RUNNING tasks older than threshold as FAILED.

    Returns count of reaped rows. Idempotent: subsequent calls find
    nothing если все tasks fresh.

    Pure-bulk UPDATE — не trigger'ит per-row hooks. Audit запись не
    создаём (это housekeeping, не actionable security event).
    """
    cutoff = (now or datetime.now(UTC)) - threshold
    async with session_factory() as session:
        stmt = (
            update(AdminTask)
            .where(
                AdminTask.status.in_(["PENDING", "RUNNING"]),
                AdminTask.created_at < cutoff,
            )
            .values(
                status="FAILED",
                error="reaper: orphaned after process restart (>15min stale)",
                completed_at=now or datetime.now(UTC),
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        reaped = result.rowcount or 0
        if reaped:
            logger.warning(
                "admin_tasks.reaper.reaped",
                extra={"count": reaped, "threshold_minutes": int(threshold.total_seconds() / 60)},
            )
        else:
            logger.info("admin_tasks.reaper.nothing_to_reap")
        return reaped


__all__ = ["STALE_THRESHOLD", "reap_stale_tasks"]

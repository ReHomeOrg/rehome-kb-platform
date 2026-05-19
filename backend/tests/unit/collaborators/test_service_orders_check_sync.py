"""Drift sync: service_orders_models constants ↔ migration 0024 CHECK.

Status / payment_status tuples в модели обязаны соответствовать значениям
в migration CHECK constraint. Drift = unexpected runtime CHECK violation
после deploy.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.api.collaborators.service_orders_models import (
    PAYMENT_STATUSES,
    SERVICE_ORDER_STATUSES,
)

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "20260518_020000_service_orders.py"
)


def _extract_tuple(source: str, name: str) -> set[str]:
    pattern = re.compile(rf"{re.escape(name)}\s*=\s*\((.*?)\)", re.DOTALL)
    m = pattern.search(source)
    assert m is not None, f"Constant {name} не найдена в migration"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_migration_status_values_match_model() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    migration_statuses = _extract_tuple(src, "_STATUS_VALUES")
    assert migration_statuses == set(SERVICE_ORDER_STATUSES), (
        f"Drift: model SERVICE_ORDER_STATUSES vs migration _STATUS_VALUES.\n"
        f"  model only: {set(SERVICE_ORDER_STATUSES) - migration_statuses}\n"
        f"  migration only: {migration_statuses - set(SERVICE_ORDER_STATUSES)}"
    )


def test_migration_payment_statuses_match_model() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    migration_payment = _extract_tuple(src, "_PAYMENT_STATUS_VALUES")
    assert migration_payment == set(PAYMENT_STATUSES)

"""Collaborators lifecycle transitions (ADR-0014 §5, ТЗ §3.10.2).

Pure validators — без I/O. Возвращают `LifecycleViolation` namedtuple
с reason'ами, которые router конвертит в 422 Problem Details.

Преходы Slice 2:
- DRAFT / PENDING_REVIEW → ACTIVE через `/activate`
- ACTIVE → SUSPENDED через `/suspend`
- SUSPENDED → ACTIVE через `/activate` (re-activation, тот же endpoint)

Архивация (ARCHIVED) — отдельный flow через DELETE (Slice 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LifecycleViolation:
    """Один invariant violation — поле + причина."""

    field: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "reason": self.reason}


# Статусы из которых разрешён переход в ACTIVE через /activate.
_ACTIVATE_FROM_STATUSES = frozenset({"DRAFT", "PENDING_REVIEW", "SUSPENDED"})

# Статусы из которых разрешён переход в SUSPENDED через /suspend.
_SUSPEND_FROM_STATUSES = frozenset({"ACTIVE"})

# Финансовые группы требующие договора (A/B/C — есть денежные отношения).
_GROUPS_REQUIRING_CONTRACT = frozenset({"A", "B", "C"})


def validate_activation(
    *,
    current_status: str,
    financial_group: str,
    counterparty_check: dict[str, Any],
    contract_document_id: Any,
    responsible_internal: str | None,
) -> list[LifecycleViolation]:
    """Проверки перед DRAFT/PENDING_REVIEW/SUSPENDED → ACTIVE (ТЗ §3.10.2).

    Returns пустой list если всё ОК; иначе — все нарушения сразу
    (быстрее UX чем один-за-другим).
    """
    violations: list[LifecycleViolation] = []

    if current_status not in _ACTIVATE_FROM_STATUSES:
        violations.append(
            LifecycleViolation(
                field="status",
                reason=(
                    f"Активация возможна только из "
                    f"{sorted(_ACTIVATE_FROM_STATUSES)}, текущий статус: "
                    f"{current_status}"
                ),
            )
        )

    # counterparty_check.result должен быть CLEAN (per ТЗ §10.5).
    # Структура: {result: CLEAN/YELLOW/RED, checked_at: ISO8601, expires_at: ...}.
    # Группа D не требует — публичные/городские службы.
    if financial_group != "D":
        cp_result = counterparty_check.get("result") if counterparty_check else None
        if cp_result != "CLEAN":
            violations.append(
                LifecycleViolation(
                    field="counterparty_check.result",
                    reason=(
                        f"Требуется CLEAN для активации группы "
                        f"{financial_group}, текущий: {cp_result!r}"
                    ),
                )
            )

    # Договор обязателен для групп A/B/C (ТЗ §10.4).
    if financial_group in _GROUPS_REQUIRING_CONTRACT and not contract_document_id:
        violations.append(
            LifecycleViolation(
                field="contract_document_id",
                reason=(
                    f"Обязателен договор (contract_document_id) для группы " f"{financial_group}"
                ),
            )
        )

    # Ответственный сотрудник обязателен для всех кроме D (D — публичные
    # контакты без операционной нагрузки).
    if financial_group != "D" and not responsible_internal:
        violations.append(
            LifecycleViolation(
                field="responsible_internal",
                reason=(f"Требуется responsible_internal для группы " f"{financial_group}"),
            )
        )

    return violations


def validate_suspension(current_status: str) -> list[LifecycleViolation]:
    """Проверка перед ACTIVE → SUSPENDED.

    Простая транзишн-проверка — только из ACTIVE. SUSPENDED→SUSPENDED
    не запрещён логически, но запрещаем чтобы было idempotent-friendly
    (caller знает что delta была).
    """
    if current_status not in _SUSPEND_FROM_STATUSES:
        return [
            LifecycleViolation(
                field="status",
                reason=(
                    f"Приостановка возможна только из "
                    f"{sorted(_SUSPEND_FROM_STATUSES)}, текущий статус: "
                    f"{current_status}"
                ),
            )
        ]
    return []


__all__ = ["LifecycleViolation", "validate_activation", "validate_suspension"]

"""In-memory rate-limiter для public endpoints (ADR-0015 §7).

Token-bucket-style — sliding window. Per-process state.

**Production caveat**: in-memory state теряется при rolling deploy / pod
restart. Acceptable для MVP single-pod local-dev; production требует
distributed implementation (Redis или nginx-level limit) — backlog.

`X-Forwarded-For` trust только для `TRUSTED_PROXIES` env config —
anti-spoof. Default fallback: `request.client.host`.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Final

from fastapi import HTTPException, Request

# ADR-0015 §2 — 5 заявок / IP / час. Conservative для MVP, проверим
# реальный объём в metrics + поднимем если нужно.
_MAX_REQUESTS: Final[int] = 5
_WINDOW_SECONDS: Final[int] = 3600


class IPRateLimiter:
    """Sliding-window rate-limit by client IP.

    Бакеты в module-global dict — per-process, per-restart. Каждый bucket
    хранит timestamps последних запросов; reqs старше окна выбрасываются
    при следующем check.

    Memory bound: O(unique_ips * max_requests). MVP с 5 req/hour/IP —
    O(daily-unique-IPs × 5) ~ << 1MB. Cleanup происходит лениво при
    каждом check (старые записи отбрасываются).
    """

    def __init__(
        self,
        *,
        max_requests: int = _MAX_REQUESTS,
        window_seconds: int = _WINDOW_SECONDS,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._windows: dict[str, list[float]] = {}

    def check_and_record(self, ip: str) -> bool:
        """True — request allowed; False — rate-limit exceeded.

        Side-effect: успешный check append'ит timestamp в bucket. При
        failure ничего не пишет — анти-amplification (атакующий не может
        раздувать память бесконечно)."""
        now = time.time()
        bucket = self._windows.get(ip)
        if bucket is None:
            bucket = []
            self._windows[ip] = bucket
        # Lazy cleanup — выкидываем timestamps старше окна.
        bucket[:] = [t for t in bucket if now - t < self._window_seconds]
        if len(bucket) >= self._max_requests:
            return False
        bucket.append(now)
        return True

    def reset(self) -> None:
        """Очищает все buckets — для тестов."""
        self._windows.clear()


# Module-level singleton — shared между request handlers одного процесса.
_GLOBAL_LIMITER = IPRateLimiter()


def _trusted_proxies() -> set[str]:
    """Set IP'ов whose X-Forwarded-For мы доверяем.

    Empty по умолчанию — significantly safer (anti-spoof). Production deploy
    обновляет через env `TRUSTED_PROXIES=10.0.0.1,10.0.0.2`.
    """
    raw = os.environ.get("TRUSTED_PROXIES", "").strip()
    if not raw:
        return set()
    return {ip.strip() for ip in raw.split(",") if ip.strip()}


def extract_client_ip(request: Request) -> str:
    """Возвращает client IP с anti-spoof guards.

    Если request пришёл от trusted proxy (env TRUSTED_PROXIES) — берём
    первый IP из X-Forwarded-For. Иначе — request.client.host (TCP peer).

    Empty/missing client → "unknown" (rate-limit bucket один на всех
    unknown-ов; conservative).
    """
    peer = request.client.host if request.client else None
    if peer is None:
        return "unknown"
    trusted = _trusted_proxies()
    if peer in trusted:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            # Берём первый IP — клиентский (RFC 7239 §5.2).
            return xff.split(",")[0].strip() or peer
    return peer


def hash_ip(ip: str) -> str:
    """SHA256[:16] hex digest IP — для audit log per ФЗ-152.

    Plain IP — это persistent identifier (требует обоснования retention
    >30 дней). Hashed IP позволяет audit search (find все ops с этого IP)
    без хранения исходного значения. Не reversible.
    """
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def enforce_onboarding_rate_limit(request: Request) -> str:
    """FastAPI dependency: проверка rate-limit + возврат hashed IP.

    Raises:
        HTTPException(429) — если превышен лимит.

    Returns:
        hashed IP (для audit metadata).
    """
    ip = extract_client_ip(request)
    if not _GLOBAL_LIMITER.check_and_record(ip):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Превышен лимит {_MAX_REQUESTS} заявок/час. "
                "Свяжитесь со staff-командой напрямую."
            ),
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )
    return hash_ip(ip)


def reset_global_limiter() -> None:
    """Reset для тестов (autouse fixture)."""
    _GLOBAL_LIMITER.reset()


__all__ = [
    "IPRateLimiter",
    "enforce_onboarding_rate_limit",
    "extract_client_ip",
    "hash_ip",
    "reset_global_limiter",
]

"""Unit tests для ratelimit module (ADR-0015 §7)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.api.collaborators.ratelimit import (
    IPRateLimiter,
    extract_client_ip,
    hash_ip,
)

# ---------------------------------------------------------------------------
# IPRateLimiter


def test_first_request_allowed() -> None:
    rl = IPRateLimiter(max_requests=3, window_seconds=60)
    assert rl.check_and_record("1.2.3.4") is True


def test_within_limit_all_allowed() -> None:
    rl = IPRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        assert rl.check_and_record("1.2.3.4") is True


def test_exceeds_limit_returns_false() -> None:
    rl = IPRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        rl.check_and_record("1.2.3.4")
    assert rl.check_and_record("1.2.3.4") is False


def test_failed_check_does_not_grow_bucket() -> None:
    """Anti-amplification: failed check не пишет в bucket."""
    rl = IPRateLimiter(max_requests=2, window_seconds=60)
    rl.check_and_record("1.2.3.4")
    rl.check_and_record("1.2.3.4")
    bucket_before = len(rl._windows["1.2.3.4"])
    rl.check_and_record("1.2.3.4")  # exceeds — should not append
    rl.check_and_record("1.2.3.4")  # exceeds — should not append
    assert len(rl._windows["1.2.3.4"]) == bucket_before


def test_different_ips_have_separate_buckets() -> None:
    rl = IPRateLimiter(max_requests=1, window_seconds=60)
    assert rl.check_and_record("1.1.1.1") is True
    assert rl.check_and_record("2.2.2.2") is True
    assert rl.check_and_record("1.1.1.1") is False
    assert rl.check_and_record("2.2.2.2") is False


def test_window_expiry_resets_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """После окна старые timestamps выкидываются."""
    rl = IPRateLimiter(max_requests=2, window_seconds=60)

    times = [100.0, 100.0, 100.0, 200.0]  # 4-й вызов через 100 сек.
    monkeypatch.setattr("src.api.collaborators.ratelimit.time.time", lambda: times.pop(0))
    rl.check_and_record("1.2.3.4")
    rl.check_and_record("1.2.3.4")
    assert rl.check_and_record("1.2.3.4") is False  # limit hit at t=100
    # t=200: 100s passed > 60s window → old timestamps cleared
    assert rl.check_and_record("1.2.3.4") is True


def test_reset_clears_state() -> None:
    rl = IPRateLimiter(max_requests=1, window_seconds=60)
    rl.check_and_record("1.2.3.4")
    rl.reset()
    assert rl.check_and_record("1.2.3.4") is True


# ---------------------------------------------------------------------------
# extract_client_ip — anti-spoof


def _fake_request(host: str | None, headers: dict[str, str] | None = None) -> MagicMock:
    r = MagicMock()
    if host is None:
        r.client = None
    else:
        r.client = MagicMock(host=host)
    r.headers = headers or {}
    return r


def test_extract_uses_request_client_host_by_default() -> None:
    req = _fake_request("203.0.113.1", headers={"X-Forwarded-For": "evil.com"})
    # No TRUSTED_PROXIES env → XFF ignored.
    assert extract_client_ip(req) == "203.0.113.1"


def test_extract_uses_xff_only_for_trusted_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1")
    req = _fake_request("10.0.0.1", headers={"X-Forwarded-For": "203.0.113.42, 10.0.0.1"})
    assert extract_client_ip(req) == "203.0.113.42"


def test_extract_falls_back_to_peer_for_untrusted_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1")
    req = _fake_request("10.0.0.99", headers={"X-Forwarded-For": "evil.com"})
    assert extract_client_ip(req) == "10.0.0.99"


def test_extract_handles_missing_client() -> None:
    req = _fake_request(None)
    assert extract_client_ip(req) == "unknown"


# ---------------------------------------------------------------------------
# hash_ip


def test_hash_ip_deterministic() -> None:
    assert hash_ip("1.2.3.4") == hash_ip("1.2.3.4")


def test_hash_ip_different_for_different_inputs() -> None:
    assert hash_ip("1.2.3.4") != hash_ip("5.6.7.8")


def test_hash_ip_is_16_hex_chars() -> None:
    h = hash_ip("1.2.3.4")
    assert len(h) == 16
    int(h, 16)  # raises ValueError if not hex

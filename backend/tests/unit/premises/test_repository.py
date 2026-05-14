"""Unit tests для PremisesRepository — status filter (#142)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.auth.scope import AccessLevel
from src.api.premises.repository import PremisesRepository, decode_cursor, encode_cursor

# ---------------------------------------------------------------------------
# _visible_statuses pure logic


def test_visible_statuses_anon() -> None:
    """PUBLIC only — видит только PUBLISHED + RENTED."""
    s = PremisesRepository._visible_statuses(frozenset({AccessLevel.PUBLIC}))
    assert set(s) == {"PUBLISHED", "RENTED"}


def test_visible_statuses_tenant() -> None:
    s = PremisesRepository._visible_statuses(frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}))
    assert set(s) == {"PUBLISHED", "RENTED"}


def test_visible_statuses_staff_sees_all() -> None:
    s = PremisesRepository._visible_statuses(
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.STAFF})
    )
    assert set(s) == {"DRAFT", "PUBLISHED", "RENTED", "ARCHIVED"}


def test_visible_statuses_legal_sees_all() -> None:
    s = PremisesRepository._visible_statuses(frozenset({AccessLevel.LEGAL}))
    assert set(s) == {"DRAFT", "PUBLISHED", "RENTED", "ARCHIVED"}


# ---------------------------------------------------------------------------
# get_by_slug SQL inspection (ADR-0003 invariant)


@pytest.mark.asyncio
async def test_get_by_slug_applies_status_filter_for_anon() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    repo = PremisesRepository(session)
    await repo.get_by_slug("test", frozenset({AccessLevel.PUBLIC}))
    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert "PUBLISHED" in flat
    assert "RENTED" in flat
    # DRAFT / ARCHIVED НЕ в params для anon.
    assert "DRAFT" not in flat
    assert "ARCHIVED" not in flat


@pytest.mark.asyncio
async def test_get_by_slug_staff_includes_all_statuses() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    repo = PremisesRepository(session)
    await repo.get_by_slug("test", frozenset({AccessLevel.STAFF}))
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert "DRAFT" in flat
    assert "ARCHIVED" in flat


# ---------------------------------------------------------------------------
# cursor codec


def test_encode_decode_roundtrip() -> None:
    cursor = encode_cursor("2026-05-14T01:00:00+00:00", "abc-123")
    decoded = decode_cursor(cursor)
    assert decoded == ("2026-05-14T01:00:00+00:00", "abc-123")


def test_decode_malformed_returns_none() -> None:
    assert decode_cursor("!!!not-base64!!!") is None
    assert decode_cursor("") is None


def test_decode_missing_separator_returns_none() -> None:
    """Base64 без `|` разделителя → malformed."""
    from base64 import urlsafe_b64encode

    raw = urlsafe_b64encode(b"no-separator").decode("ascii").rstrip("=")
    assert decode_cursor(raw) is None

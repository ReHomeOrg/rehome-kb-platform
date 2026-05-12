"""Тесты opaque cursor encode/decode.

cursor — это контракт с клиентом; любое поломка decode → 400, не 500.
"""

import base64
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.api.articles.cursor import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)


def test_encode_decode_roundtrip() -> None:
    ts = datetime(2026, 5, 12, 10, 30, 0, tzinfo=UTC)
    article_id = uuid4()
    encoded = encode_cursor(ts, article_id)
    decoded_ts, decoded_id = decode_cursor(encoded)
    assert decoded_ts == ts
    assert decoded_id == article_id


def test_encoded_cursor_is_urlsafe() -> None:
    """В URL не должно потребоваться percent-encoding."""
    encoded = encode_cursor(datetime(2026, 5, 12, tzinfo=UTC), uuid4())
    # urlsafe_b64encode исключает `+`, `/`, `=` (padding мы тоже не оставляем).
    assert "+" not in encoded
    assert "/" not in encoded


def test_decode_invalid_base64_raises() -> None:
    with pytest.raises(InvalidCursorError) as exc_info:
        decode_cursor("это не base64 ©®")
    assert exc_info.value.status_code == 400


def test_decode_invalid_json_raises() -> None:
    raw = base64.urlsafe_b64encode(b"not json {{{").decode("ascii")
    with pytest.raises(InvalidCursorError) as exc_info:
        decode_cursor(raw)
    assert exc_info.value.status_code == 400


def test_decode_non_object_json_raises() -> None:
    raw = base64.urlsafe_b64encode(b'["array", "not", "object"]').decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw)


def test_decode_missing_u_field_raises() -> None:
    raw = base64.urlsafe_b64encode(b'{"i": "00000000-0000-0000-0000-000000000000"}').decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw)


def test_decode_missing_i_field_raises() -> None:
    raw = base64.urlsafe_b64encode(b'{"u": "2026-05-12T00:00:00+00:00"}').decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw)


def test_decode_invalid_iso8601_raises() -> None:
    raw = base64.urlsafe_b64encode(
        b'{"u": "not-a-date", "i": "00000000-0000-0000-0000-000000000000"}'
    ).decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw)


def test_decode_invalid_uuid_raises() -> None:
    raw = base64.urlsafe_b64encode(b'{"u": "2026-05-12T00:00:00+00:00", "i": "not-a-uuid"}').decode(
        "ascii"
    )
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw)


def test_decode_non_string_fields_raise() -> None:
    raw = base64.urlsafe_b64encode(b'{"u": 12345, "i": 67890}').decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw)


def test_decoded_uuid_is_uuid_type() -> None:
    ts = datetime(2026, 5, 12, tzinfo=UTC)
    aid = UUID("11111111-2222-3333-4444-555555555555")
    _, decoded_id = decode_cursor(encode_cursor(ts, aid))
    assert isinstance(decoded_id, UUID)

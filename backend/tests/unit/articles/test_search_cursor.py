"""Тесты score-cursor для search (E2.5a #46)."""

import base64
from uuid import UUID, uuid4

import pytest

from src.api.articles.cursor import (
    InvalidCursorError,
    decode_score_cursor,
    encode_score_cursor,
)


def test_encode_decode_score_cursor_roundtrip() -> None:
    score = 0.5123
    aid = uuid4()
    encoded = encode_score_cursor(score, aid)
    decoded_score, decoded_id = decode_score_cursor(encoded)
    assert abs(decoded_score - score) < 1e-9
    assert decoded_id == aid


def test_encode_score_cursor_is_urlsafe() -> None:
    encoded = encode_score_cursor(0.5, uuid4())
    assert "+" not in encoded
    assert "/" not in encoded


def test_decode_score_cursor_invalid_base64_raises() -> None:
    with pytest.raises(InvalidCursorError):
        decode_score_cursor("это не base64 ©")


def test_decode_score_cursor_invalid_json_raises() -> None:
    raw = base64.urlsafe_b64encode(b"not json {{{").decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_score_cursor(raw)


def test_decode_score_cursor_missing_fields_raises() -> None:
    raw = base64.urlsafe_b64encode(b'{"i": "00000000-0000-0000-0000-000000000000"}').decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_score_cursor(raw)


def test_decode_score_cursor_score_not_number_raises() -> None:
    raw = base64.urlsafe_b64encode(
        b'{"s": "not-a-number", "i": "00000000-0000-0000-0000-000000000000"}'
    ).decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_score_cursor(raw)


def test_decode_score_cursor_invalid_uuid_raises() -> None:
    raw = base64.urlsafe_b64encode(b'{"s": 0.5, "i": "not-a-uuid"}').decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode_score_cursor(raw)


def test_decoded_score_id_types() -> None:
    aid = UUID("11111111-2222-3333-4444-555555555555")
    encoded = encode_score_cursor(0.9, aid)
    score, decoded = decode_score_cursor(encoded)
    assert isinstance(score, float)
    assert isinstance(decoded, UUID)

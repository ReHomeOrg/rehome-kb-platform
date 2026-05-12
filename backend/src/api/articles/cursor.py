"""Opaque cursor для keyset-пагинации `GET /api/v1/articles`.

Формат: `urlsafe_base64(json.dumps({"u": "<iso8601>", "i": "<uuid>"}))`.

`u` — `updated_at` ISO8601 с TZ (UTC), `i` — UUID строкой. Эта пара —
стабильный sort key `ORDER BY updated_at DESC, id DESC` (см. docstring
`ArticleRepository.list_filtered`).

ВАЖНО: cursor **opaque-by-convention** — клиент не должен парсить его
структуру и полагаться на формат. Если в будущем потребуется положить в
cursor чувствительные данные (например, scope hash или offset), нужно
переходить на signed/encrypted token (`itsdangerous.TimestampSigner` или
JWT с server-side secret). Сейчас защиты нет — поэтому в cursor
запрещено класть что-либо, кроме «публично выводимых» полей строки.
"""

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status


class InvalidCursorError(HTTPException):
    """HTTP 400 — клиент прислал битый cursor.

    Намеренно отдельная ошибка (не молчаливое игнорирование) — это
    позволяет клиенту понять, что он что-то делает не так, а нам — поймать
    атаки/баги через access logs.
    """

    def __init__(self, detail: str = "Invalid cursor") -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


def encode_cursor(updated_at: datetime, article_id: UUID) -> str:
    """Кодирует пару (updated_at, id) в opaque urlsafe-base64-JSON строку."""
    payload = json.dumps({"u": updated_at.isoformat(), "i": str(article_id)})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(raw: str) -> tuple[datetime, UUID]:
    """Декодирует opaque cursor → `(updated_at, id)`.

    Поднимает `InvalidCursorError` (HTTP 400) при любой проблеме: невалидный
    base64, невалидный JSON, отсутствующие/невалидные поля. Любой 500
    из-за битого ввода клиента — баг.
    """
    try:
        padded = raw + "=" * (-len(raw) % 4)
        data = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise InvalidCursorError(detail="Cursor is not valid base64") from exc

    try:
        parsed = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidCursorError(detail="Cursor is not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise InvalidCursorError(detail="Cursor payload must be an object")

    raw_u = parsed.get("u")
    raw_i = parsed.get("i")
    if not isinstance(raw_u, str) or not isinstance(raw_i, str):
        raise InvalidCursorError(detail="Cursor missing required fields")

    try:
        updated_at = datetime.fromisoformat(raw_u)
    except ValueError as exc:
        raise InvalidCursorError(detail="Cursor 'u' is not valid ISO8601") from exc

    try:
        article_id = UUID(raw_i)
    except ValueError as exc:
        raise InvalidCursorError(detail="Cursor 'i' is not valid UUID") from exc

    return updated_at, article_id


def encode_score_cursor(score: float, article_id: UUID) -> str:
    """Кодирует пару `(score, article_id)` для search-pagination (E2.5a #46).

    Score — float от `ts_rank`. ID — UUID статьи (tiebreaker для стабильной
    сортировки при одинаковом score).

    NB: cursor валиден только для **стабильного `q`**. Если client меняет
    query — должен делать fresh search (rank-distribution меняется).
    """
    payload = json.dumps({"s": score, "i": str(article_id)})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_score_cursor(raw: str) -> tuple[float, UUID]:
    """Декодирует opaque score-cursor → `(score, article_id)`.

    400 на битый base64/JSON/missing fields/wrong types.
    """
    try:
        padded = raw + "=" * (-len(raw) % 4)
        data = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise InvalidCursorError(detail="Cursor is not valid base64") from exc

    try:
        parsed = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidCursorError(detail="Cursor is not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise InvalidCursorError(detail="Cursor payload must be an object")

    raw_s = parsed.get("s")
    raw_i = parsed.get("i")
    if not isinstance(raw_s, int | float) or not isinstance(raw_i, str):
        raise InvalidCursorError(detail="Cursor missing required fields")

    try:
        article_id = UUID(raw_i)
    except ValueError as exc:
        raise InvalidCursorError(detail="Cursor 'i' is not valid UUID") from exc

    return float(raw_s), article_id

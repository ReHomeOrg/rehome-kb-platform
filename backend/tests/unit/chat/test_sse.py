"""Unit-тесты `format_sse_event` (E3.4 #67)."""

from src.api.chat.sse import format_sse_event


def test_format_basic_event() -> None:
    result = format_sse_event("chunk", {"text": "hello"})
    assert result == 'event: chunk\ndata: {"text":"hello"}\n\n'


def test_format_event_ends_with_double_newline() -> None:
    """SSE spec: event terminator — пустая строка (\\n\\n)."""
    result = format_sse_event("done", {})
    assert result.endswith("\n\n")


def test_format_data_is_single_line() -> None:
    """compact JSON → нет внутренних newlines в data."""
    result = format_sse_event("chunk", {"text": "multi\nline"})
    data_line = result.split("\n")[1]  # event: X, data: Y, '', ''
    # JSON escape'нет \\n как \\\\n — никаких bare newlines в data:
    assert data_line.startswith("data: ")
    payload = data_line[len("data: ") :]
    assert "\n" not in payload


def test_format_cyrillic_in_data_not_escaped() -> None:
    """ensure_ascii=False — кириллица в data как есть (не \\uXXXX)."""
    result = format_sse_event("chunk", {"text": "Привет"})
    assert "Привет" in result
    assert "\\u" not in result


def test_format_nested_dict() -> None:
    result = format_sse_event(
        "message-end",
        {"message_id": "abc", "total_tokens": 42},
    )
    assert "message_id" in result
    assert "total_tokens" in result
    assert "42" in result


def test_format_empty_data_payload() -> None:
    result = format_sse_event("done", {})
    assert result == "event: done\ndata: {}\n\n"

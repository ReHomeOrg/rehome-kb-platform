"""Unit tests для JSON log formatter (#110)."""

import json
import logging
from io import StringIO

from src.api.observability.log_format import (
    JsonLogFormatter,
    install_json_log_formatter,
)


def _make_record(
    *,
    level: int = logging.INFO,
    msg: str = "hello",
    args: tuple[object, ...] = (),
    name: str = "test.logger",
    extra: dict[str, object] | None = None,
    exc_info: object | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,  # type: ignore[arg-type]
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# Output format


def test_formatter_produces_valid_json() -> None:
    record = _make_record()
    out = JsonLogFormatter().format(record)
    parsed = json.loads(out)
    assert isinstance(parsed, dict)


def test_formatter_includes_core_fields() -> None:
    record = _make_record(level=logging.WARNING, msg="hello %s", args=("world",))
    parsed = json.loads(JsonLogFormatter().format(record))
    assert parsed["level"] == "WARNING"
    assert parsed["logger"] == "test.logger"
    assert parsed["message"] == "hello world"
    assert "timestamp" in parsed


def test_formatter_includes_request_id_when_attr_set() -> None:
    """Field выставляется фильтром #106, formatter забирает через getattr."""
    record = _make_record(extra={"request_id": "abc-123"})
    parsed = json.loads(JsonLogFormatter().format(record))
    assert parsed["request_id"] == "abc-123"


def test_formatter_uses_sentinel_when_request_id_missing() -> None:
    record = _make_record()
    parsed = json.loads(JsonLogFormatter().format(record))
    assert parsed["request_id"] == "-"


# ---------------------------------------------------------------------------
# Extra fields whitelist


def test_formatter_surfaces_extra_fields() -> None:
    record = _make_record(extra={"event": "articles.created", "slug": "x"})
    parsed = json.loads(JsonLogFormatter().format(record))
    assert parsed["event"] == "articles.created"
    assert parsed["slug"] == "x"


def test_formatter_excludes_internal_logrecord_attrs() -> None:
    """`created`/`msecs`/`pathname`/etc. — internal Python logging attrs,
    в JSON output не должны попадать (loud-shape noise)."""
    record = _make_record()
    parsed = json.loads(JsonLogFormatter().format(record))
    for noise_key in ("created", "msecs", "pathname", "lineno", "funcName", "args"):
        assert noise_key not in parsed


# ---------------------------------------------------------------------------
# Exception handling


def test_formatter_emits_exception_traceback_as_string() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record(exc_info=sys.exc_info())
    parsed = json.loads(JsonLogFormatter().format(record))
    assert "exception" in parsed
    assert "ValueError" in parsed["exception"]
    assert "boom" in parsed["exception"]


# ---------------------------------------------------------------------------
# Non-serializable extras


def test_formatter_falls_back_to_str_for_non_serializable() -> None:
    """`default=str` ловит UUID/datetime/etc. без падения."""
    from uuid import UUID

    record = _make_record(extra={"id": UUID("550e8400-e29b-41d4-a716-446655440000")})
    parsed = json.loads(JsonLogFormatter().format(record))
    assert parsed["id"] == "550e8400-e29b-41d4-a716-446655440000"


# ---------------------------------------------------------------------------
# install_json_log_formatter


def test_install_replaces_formatter_on_existing_handler() -> None:
    """Если у root уже есть handler — formatter replace'ится."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    try:
        root.handlers.clear()
        existing = logging.StreamHandler(StringIO())
        existing.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(existing)

        install_json_log_formatter()

        assert isinstance(existing.formatter, JsonLogFormatter)
    finally:
        root.handlers.clear()
        for h in saved_handlers:
            root.addHandler(h)


def test_install_adds_handler_when_none_exist() -> None:
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    try:
        root.handlers.clear()
        install_json_log_formatter()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
    finally:
        root.handlers.clear()
        for h in saved_handlers:
            root.addHandler(h)


def test_install_is_idempotent_does_not_duplicate_handlers() -> None:
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    try:
        root.handlers.clear()
        install_json_log_formatter()
        install_json_log_formatter()
        install_json_log_formatter()
        # Не больше одного handler'а — повторные install'ы должны переустанавливать
        # formatter на существующий handler, не плодить дубликаты.
        assert len(root.handlers) == 1
    finally:
        root.handlers.clear()
        for h in saved_handlers:
            root.addHandler(h)


# ---------------------------------------------------------------------------
# End-to-end: RequestIdLogFilter + JsonLogFormatter chain — raison d'être #111.


def test_filter_and_formatter_chain_surfaces_request_id_e2e() -> None:
    """`install_request_id_filter()` + `install_json_log_formatter()` + real
    `logger.info()` → JSON output должен содержать current request_id
    из contextvar (#106 → #110 chain). Это central goal этой PR'а."""
    from src.api.observability import (
        REQUEST_ID_CONTEXT,
        install_request_id_filter,
    )

    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_filters = list(root.filters)
    saved_level = root.level
    try:
        root.handlers.clear()
        root.filters.clear()
        # Direct stream capture (вместо stderr → нужны test-time isolation).
        capture = StringIO()
        handler = logging.StreamHandler(capture)
        handler.setFormatter(JsonLogFormatter())
        root.addHandler(handler)
        root.setLevel(logging.INFO)

        install_request_id_filter()

        token = REQUEST_ID_CONTEXT.set("e2e-request-id-xyz")
        try:
            logging.getLogger("test.chain").info("chain works", extra={"event": "test.chain"})
        finally:
            REQUEST_ID_CONTEXT.reset(token)

        line = capture.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["request_id"] == "e2e-request-id-xyz"
        assert parsed["message"] == "chain works"
        assert parsed["event"] == "test.chain"
        assert parsed["level"] == "INFO"
    finally:
        root.handlers.clear()
        root.filters.clear()
        for h in saved_handlers:
            root.addHandler(h)
        for f in saved_filters:
            root.addFilter(f)
        root.setLevel(saved_level)


# ---------------------------------------------------------------------------
# install_request_id_filter idempotency (#106, see logging.py:42-57)


def test_install_filter_no_handlers_idempotent_skip() -> None:
    """Root без handlers → filter ставится на root.filters. Повторный
    install должен skip'нуть (RequestIdLogFilter уже в root.filters)."""
    from src.api.observability import RequestIdLogFilter, install_request_id_filter

    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_filters = list(root.filters)
    try:
        root.handlers.clear()
        root.filters.clear()

        install_request_id_filter()
        first_count = sum(1 for f in root.filters if isinstance(f, RequestIdLogFilter))
        assert first_count == 1

        install_request_id_filter()  # idempotent — не должен добавить второй
        second_count = sum(1 for f in root.filters if isinstance(f, RequestIdLogFilter))
        assert second_count == 1, "RequestIdLogFilter дублирован в root.filters"
    finally:
        root.handlers.clear()
        root.filters.clear()
        for h in saved_handlers:
            root.addHandler(h)
        for f in saved_filters:
            root.addFilter(f)


def test_install_filter_handler_already_has_filter_skip() -> None:
    """Handler с filter'ом уже стоящим → install skip'ает его без duplicate."""
    from src.api.observability import RequestIdLogFilter, install_request_id_filter

    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_filters = list(root.filters)
    try:
        root.handlers.clear()
        root.filters.clear()
        handler = logging.StreamHandler(StringIO())
        root.addHandler(handler)

        install_request_id_filter()
        first_count = sum(1 for f in handler.filters if isinstance(f, RequestIdLogFilter))
        assert first_count == 1

        install_request_id_filter()  # second call must skip
        second_count = sum(1 for f in handler.filters if isinstance(f, RequestIdLogFilter))
        assert second_count == 1, "Filter дублирован на handler.filters"
    finally:
        root.handlers.clear()
        root.filters.clear()
        for h in saved_handlers:
            root.addHandler(h)
        for f in saved_filters:
            root.addFilter(f)

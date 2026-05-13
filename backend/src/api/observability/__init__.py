"""Observability primitives — request-id propagation, structured logging.

Issue #106: closing the gap between OpenAPI 04 `X-Request-Id` parameter и
runtime backend (раньше header не читался, не генерировался, не возвращался).
"""

from src.api.observability.context import (
    REQUEST_ID_CONTEXT,
    REQUEST_ID_HEADER,
    get_request_id,
)
from src.api.observability.logging import RequestIdLogFilter, install_request_id_filter
from src.api.observability.request_id import RequestIdMiddleware

__all__ = [
    "REQUEST_ID_CONTEXT",
    "REQUEST_ID_HEADER",
    "RequestIdLogFilter",
    "RequestIdMiddleware",
    "get_request_id",
    "install_request_id_filter",
]

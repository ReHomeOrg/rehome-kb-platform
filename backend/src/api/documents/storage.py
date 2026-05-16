"""MinIO client wrapper для documents (#214, ADR-0012 Phase A).

Single bucket model — `rehome-kb-files`. Storage key matches TZ §3.2
hierarchy:

    legal/<category_subdir>/<doc_id>/<version>/<format>.<ext>

`category_subdir`:
- A → external
- B → contracts
- C → partners
- D → internal
- E → regulators
- F → templates

В Phase A — read path: parse stored `storage_key` из `documents.files[*].
storage_key` и generates presigned GET URL с TTL `signed_url_ttl_seconds`.

Phase B (write) дополнит этим модулем `put_object` + key construction
helpers.

Дизайн: ленивая инициализация клиента (singleton-per-process через
module-level get_minio_client). MinIO client thread-safe; FastAPI
worker создаёт один на process.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from minio import Minio

    from src.api.config import Settings

logger = logging.getLogger(__name__)

# Public alias map TZ §3.2.
_CATEGORY_SUBDIR: Final[dict[str, str]] = {
    "A": "external",
    "B": "contracts",
    "C": "partners",
    "D": "internal",
    "E": "regulators",
    "F": "templates",
}


# Module-level singleton — lazy initialized.
_client: Minio | None = None


class StorageError(Exception):
    """Generic storage layer error.

    Router transforms in 502/503 based on `transient` flag.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class StorageNotConfiguredError(StorageError):
    """`minio_enabled=False` — функционал не доступен.

    Router transforms в 503 для signals «config issue, не data issue».
    """

    def __init__(self) -> None:
        super().__init__("MinIO storage не сконфигурирован", transient=False)


def category_subdir(category: str) -> str:
    """Map category A-F → folder subdir per TZ §3.2."""
    try:
        return _CATEGORY_SUBDIR[category]
    except KeyError as exc:
        raise ValueError(f"Unknown category {category!r}, expected one of A-F") from exc


def get_minio_client(settings: Settings) -> Minio:
    """Lazy initialize singleton MinIO client.

    Импорт `minio` ленивый чтобы dependency был soft — main API container
    не требует MinIO на boot если `MINIO_ENABLED=False` (CI default).
    """
    global _client
    if _client is not None:
        return _client
    if not settings.minio_enabled:
        raise StorageNotConfiguredError()
    # Lazy import — `minio` пакет добавлен в requirements.txt; deps
    # уже подняты в production контейнере. CI default `MINIO_ENABLED=False`
    # — import также skip'нут при отсутствии package'а.
    from minio import Minio

    _client = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    logger.info(
        "documents.storage.client_initialized",
        extra={"endpoint": settings.minio_endpoint, "bucket": settings.minio_bucket},
    )
    return _client


def reset_client_cache() -> None:
    """Clear singleton — для тестов."""
    global _client
    _client = None


def presigned_get_url(
    settings: Settings,
    storage_key: str,
) -> str:
    """Generate presigned GET URL с TTL `signed_url_ttl_seconds`.

    Raises:
        StorageNotConfiguredError: `MINIO_ENABLED=False`.
        StorageError(transient=True): MinIO unreachable / 5xx.
    """
    client = get_minio_client(settings)
    # Lazy re-import — нужен S3Error для исключений.
    from minio.error import S3Error

    try:
        url = client.presigned_get_object(
            bucket_name=settings.minio_bucket,
            object_name=storage_key,
            expires=timedelta(seconds=settings.signed_url_ttl_seconds),
        )
    except S3Error as exc:
        # MinIO returned error — most likely 5xx или object missing.
        # Transient: caller retries; non-transient: missing object → bug.
        # S3Error.code хранит string error code (NoSuchKey, etc.).
        transient = exc.code in ("InternalError", "SlowDown", "ServiceUnavailable")
        logger.warning(
            "documents.storage.s3_error",
            extra={"code": exc.code, "key": storage_key, "transient": transient},
        )
        raise StorageError(f"MinIO error: {exc.code}", transient=transient) from exc
    except Exception as exc:
        # Network-level — connection refused, DNS, TLS — transient.
        logger.warning(
            "documents.storage.network_error",
            extra={"key": storage_key, "error": str(exc)},
        )
        raise StorageError(f"MinIO unreachable: {exc!s}", transient=True) from exc
    return str(url)


_FORMAT_EXT: Final[dict[str, str]] = {
    "docx": "docx",
    "pdf": "pdf",
    "html": "html",
}


def compute_storage_key(
    *,
    category: str,
    document_id: str,
    version: str | int,
    file_format: str,
) -> str:
    """Construct MinIO object key per TZ §3.2 hierarchy.

        legal/<category_subdir>/<document_id>/<version>/<format>.<ext>

    `version` can be DB string column (e.g. "1.0") or integer counter —
    string-coerced как-есть. Format must быть docx/pdf/html.
    """
    subdir = category_subdir(category)
    if file_format not in _FORMAT_EXT:
        raise ValueError(f"Unknown file_format {file_format!r}")
    ext = _FORMAT_EXT[file_format]
    return f"legal/{subdir}/{document_id}/{version}/{file_format}.{ext}"


def upload_object(
    settings: Settings,
    storage_key: str,
    data: bytes,
    *,
    content_type: str = "application/octet-stream",
) -> None:
    """Stream `data` в MinIO bucket по `storage_key`.

    `data` — bytes (caller буферизировал). Для совсем больших файлов
    multipart-init flow — backlog. Сейчас single-shot put_object с
    Content-Length известным заранее.

    Raises:
        StorageNotConfiguredError: `MINIO_ENABLED=False`.
        StorageError(transient=True): MinIO unreachable / 5xx.
    """
    import io

    client = get_minio_client(settings)
    from minio.error import S3Error

    try:
        client.put_object(
            bucket_name=settings.minio_bucket,
            object_name=storage_key,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
    except S3Error as exc:
        transient = exc.code in ("InternalError", "SlowDown", "ServiceUnavailable")
        logger.warning(
            "documents.storage.put_s3_error",
            extra={"code": exc.code, "key": storage_key, "transient": transient},
        )
        raise StorageError(f"MinIO error: {exc.code}", transient=transient) from exc
    except Exception as exc:
        logger.warning(
            "documents.storage.put_network_error",
            extra={"key": storage_key, "error": str(exc)},
        )
        raise StorageError(f"MinIO unreachable: {exc!s}", transient=True) from exc


__all__ = [
    "StorageError",
    "StorageNotConfiguredError",
    "category_subdir",
    "compute_storage_key",
    "get_minio_client",
    "presigned_get_url",
    "reset_client_cache",
    "upload_object",
]

"""Unit tests для documents/storage MinIO wrapper (#214, ADR-0012)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.api.config import Settings
from src.api.documents.storage import (
    StorageError,
    StorageNotConfiguredError,
    category_subdir,
    presigned_get_url,
    reset_client_cache,
)


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    reset_client_cache()


def _settings(**override: object) -> Settings:
    defaults: dict[str, object] = {
        "minio_enabled": True,
        "minio_endpoint": "minio:9000",
        "minio_access_key": "k",
        "minio_secret_key": "s",
        "minio_bucket": "rehome-kb-files",
        "minio_secure": False,
        "signed_url_ttl_seconds": 300,
    }
    defaults.update(override)
    return Settings.model_validate(defaults)


# ---------------------------------------------------------------------------
# category_subdir


def test_category_subdir_maps_all_letters() -> None:
    assert category_subdir("A") == "external"
    assert category_subdir("B") == "contracts"
    assert category_subdir("C") == "partners"
    assert category_subdir("D") == "internal"
    assert category_subdir("E") == "regulators"
    assert category_subdir("F") == "templates"


def test_category_subdir_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown category"):
        category_subdir("Z")


# ---------------------------------------------------------------------------
# presigned_get_url


def test_presigned_get_url_minio_disabled_raises_not_configured() -> None:
    s = _settings(minio_enabled=False)
    with pytest.raises(StorageNotConfiguredError):
        presigned_get_url(s, "legal/external/d/1/pdf.pdf")


def test_presigned_get_url_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path — client.presigned_get_object возвращает URL string."""
    s = _settings()
    mock_client = MagicMock()
    mock_client.presigned_get_object.return_value = "https://minio/signed?x=1"

    # Patch the lazy import — `get_minio_client` returns our mock.
    import src.api.documents.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_minio_client", lambda _: mock_client)

    url = presigned_get_url(s, "legal/external/d/1/pdf.pdf")
    assert url == "https://minio/signed?x=1"
    # Verify TTL passed as timedelta(seconds=300).
    kwargs = mock_client.presigned_get_object.call_args.kwargs
    assert kwargs["bucket_name"] == "rehome-kb-files"
    assert kwargs["object_name"] == "legal/external/d/1/pdf.pdf"
    assert kwargs["expires"].total_seconds() == 300


def test_presigned_get_url_network_error_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection error → StorageError(transient=True) → 503."""
    s = _settings()
    mock_client = MagicMock()
    mock_client.presigned_get_object.side_effect = ConnectionError("refused")

    import src.api.documents.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_minio_client", lambda _: mock_client)

    with pytest.raises(StorageError) as exc_info:
        presigned_get_url(s, "k")
    assert exc_info.value.transient is True


def test_presigned_get_url_s3_error_internal_is_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Error.code='InternalError' → transient=True."""
    s = _settings()
    from minio.error import S3Error

    mock_client = MagicMock()
    mock_client.presigned_get_object.side_effect = S3Error(
        code="InternalError",
        message="boom",
        resource="x",
        request_id="r",
        host_id="h",
        response=MagicMock(),
    )

    import src.api.documents.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_minio_client", lambda _: mock_client)

    with pytest.raises(StorageError) as exc_info:
        presigned_get_url(s, "k")
    assert exc_info.value.transient is True


def test_presigned_get_url_s3_error_no_such_key_is_not_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Error.code='NoSuchKey' → transient=False → 502 (bug, not retry-able)."""
    s = _settings()
    from minio.error import S3Error

    mock_client = MagicMock()
    mock_client.presigned_get_object.side_effect = S3Error(
        code="NoSuchKey",
        message="not found",
        resource="x",
        request_id="r",
        host_id="h",
        response=MagicMock(),
    )

    import src.api.documents.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_minio_client", lambda _: mock_client)

    with pytest.raises(StorageError) as exc_info:
        presigned_get_url(s, "k")
    assert exc_info.value.transient is False

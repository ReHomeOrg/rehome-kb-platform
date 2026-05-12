"""Unit-тесты SSRF validator (E5.1 #87)."""

from unittest.mock import patch

import pytest

from src.api.webhooks.ssrf import SSRFValidationError, validate_webhook_url


def _fake_addrinfo(ip: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    return [(2, 1, 6, "", (ip, 0))]


@pytest.mark.security
def test_localhost_blocked() -> None:
    with pytest.raises(SSRFValidationError, match="private IP"):
        validate_webhook_url("http://localhost/x")


@pytest.mark.security
def test_127_0_0_1_blocked() -> None:
    with (
        patch("socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1")),
        pytest.raises(SSRFValidationError, match="private IP"),
    ):
        validate_webhook_url("http://127.0.0.1/x")


@pytest.mark.security
def test_rfc1918_10_blocked() -> None:
    with (
        patch("socket.getaddrinfo", return_value=_fake_addrinfo("10.0.0.5")),
        pytest.raises(SSRFValidationError, match="private IP"),
    ):
        validate_webhook_url("http://internal.example.com/")


@pytest.mark.security
def test_rfc1918_172_16_blocked() -> None:
    with (
        patch("socket.getaddrinfo", return_value=_fake_addrinfo("172.16.1.1")),
        pytest.raises(SSRFValidationError),
    ):
        validate_webhook_url("http://docker.example.com/")


@pytest.mark.security
def test_rfc1918_192_168_blocked() -> None:
    with (
        patch("socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.1")),
        pytest.raises(SSRFValidationError),
    ):
        validate_webhook_url("http://router.example.com/")


@pytest.mark.security
def test_link_local_169_254_blocked() -> None:
    with (
        patch("socket.getaddrinfo", return_value=_fake_addrinfo("169.254.169.254")),
        pytest.raises(SSRFValidationError),
    ):
        validate_webhook_url("http://metadata.example.com/")


@pytest.mark.security
def test_unsupported_scheme_rejected() -> None:
    with pytest.raises(SSRFValidationError, match="Scheme"):
        validate_webhook_url("ftp://example.com/x")


@pytest.mark.security
def test_file_scheme_rejected() -> None:
    with pytest.raises(SSRFValidationError, match="Scheme"):
        validate_webhook_url("file:///etc/passwd")


@pytest.mark.security
def test_public_ip_passes() -> None:
    with patch("socket.getaddrinfo", return_value=_fake_addrinfo("8.8.8.8")):
        # Should not raise
        validate_webhook_url("https://example.com/webhook")


@pytest.mark.security
def test_multiple_ips_any_private_blocks() -> None:
    """DNS rebinding mitigation: если ХОТЯ БЫ ОДИН IP private — block."""

    addrs = [
        (2, 1, 6, "", ("8.8.8.8", 0)),
        (2, 1, 6, "", ("10.0.0.1", 0)),  # internal
    ]
    with (
        patch("socket.getaddrinfo", return_value=addrs),
        pytest.raises(SSRFValidationError),
    ):
        validate_webhook_url("https://tricky.example.com/")


def test_missing_hostname_rejected() -> None:
    with pytest.raises(SSRFValidationError, match="missing hostname"):
        validate_webhook_url("http:///path")

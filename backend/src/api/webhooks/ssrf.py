"""SSRF protection для webhook URLs (E5.1 #87).

Architect decision: блокировать RFC1918 internal IPs (10/8, 172.16/12,
192.168/16, 127/8 loopback, link-local 169.254/16, multicast).
Webhook URL обязан резолвиться в public IP — иначе registration
отклоняется 400.

Backlog: DNS rebinding protection (резолв at-delivery-time), allowlist
для trusted партнёров, IPv6 ULA блок.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SSRFValidationError(Exception):
    """URL hostname резолвится в private/internal IP."""


def _is_private_ip(ip_str: str) -> bool:
    """RFC1918 + loopback + link-local + multicast → private."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # Не парсится — defensive false (не блокируем). Defensive
        # отказ был бы false-positive для странных edge case'ов.
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_webhook_url(url: str) -> None:
    """Проверяет URL на SSRF риск.

    Raises:
        SSRFValidationError если schemes не http(s) ИЛИ hostname
        резолвится в private IP.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFValidationError(f"Scheme {parsed.scheme!r} not allowed")
    if not parsed.hostname:
        raise SSRFValidationError("URL missing hostname")

    # DNS lookup. socket.getaddrinfo может вернуть несколько IPv4/IPv6 —
    # отвергаем если ХОТЯ БЫ ОДИН — private (anti-DNS-rebinding-at-save).
    try:
        addrs = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise SSRFValidationError(f"DNS resolve failed for {parsed.hostname!r}") from exc

    ips: set[str] = set()
    for addr in addrs:
        sockaddr = addr[4]
        if isinstance(sockaddr, tuple) and sockaddr:
            ips.add(str(sockaddr[0]))

    for ip in ips:
        if _is_private_ip(ip):
            logger.warning(
                "webhook.ssrf_blocked",
                extra={"hostname": parsed.hostname, "blocked_ip": ip},
            )
            raise SSRFValidationError(f"URL hostname resolves to private IP ({ip})")

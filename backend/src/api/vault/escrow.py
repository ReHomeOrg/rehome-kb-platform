"""Shamir Secret Sharing over GF(256) — emergency access (ADR-0021 A).

Pure-Python implementation, no external crypto deps beyond stdlib `secrets`.
Used для testing + reference; production combine + decrypt происходит
client-side в admin browser (см. ADR §approve note «zero-knowledge
preserved»).

Algorithm:
- Each byte of secret = independent SSS polynomial over GF(256).
- f_i(x) = secret_i + a_1·x + a_2·x² + ... + a_(t-1)·x^(t-1)
- Share k = (k, f_0(k), f_1(k), ..., f_n(k)) — 1 byte index + n bytes.
- Combine via Lagrange interpolation at x=0.

Threshold = required shares (2 для variant A). Generates n=threshold shares
(2-of-2; no extra holders). Format per share:
- `[index 1 byte][values n bytes][hmac 8 bytes]` где hmac предотвращает
  typo'ы при ручном вводе в emergency UI.

Refs:
- https://en.wikipedia.org/wiki/Shamir%27s_secret_sharing
- https://github.com/blockstack/secret-sharing (alternate reference impl)
"""

from __future__ import annotations

import base64
import hmac
import secrets
from hashlib import sha256
from typing import Final

# Standard AES key length для escrow_key.
SECRET_BYTES: Final = 32

# HMAC suffix length per share — typo detection.
HMAC_BYTES: Final = 8

# Domain-separation tag для HMAC of shares.
_HMAC_TAG: Final = b"rehome.vault.escrow.share.hmac.v1"


class EscrowError(ValueError):
    """Generic SSS error (corrupted share, threshold not met, etc.)."""


# ---------------------------------------------------------------------------
# GF(256) arithmetic — Rijndael field (same as AES).


def _gf_mul(a: int, b: int) -> int:
    """Multiplication в GF(2^8) с reduction polynomial 0x11b."""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        b >>= 1
        carry = a & 0x80
        a = (a << 1) & 0xFF
        if carry:
            a ^= 0x1B
    return p


def _gf_inv(a: int) -> int:
    """Multiplicative inverse в GF(2^8) via brute-force search.

    n=256 lookup — cost negligible vs Shamir share count (≤5)."""
    if a == 0:
        raise EscrowError("Division by zero в GF(256)")
    for x in range(1, 256):
        if _gf_mul(a, x) == 1:
            return x
    raise EscrowError("Inverse not found")  # pragma: no cover (unreachable)


# ---------------------------------------------------------------------------
# Share split / combine


def split_secret(secret: bytes, *, threshold: int = 2, n: int | None = None) -> list[bytes]:
    """Split `secret` на n shares, любые threshold из которых reconstruct'ят.

    Default: threshold=2, n=threshold (2-of-2 для variant A). Variant B
    (3-of-5) — caller передаёт threshold=3, n=5.

    Each share: [index 1B][values len(secret) B][hmac 8B]. Index = 1..n.
    """
    if threshold < 2:
        raise EscrowError(f"Threshold must be ≥2, got {threshold}")
    n_shares = n if n is not None else threshold
    if n_shares < threshold:
        raise EscrowError(f"n ({n_shares}) must be ≥ threshold ({threshold})")
    if n_shares > 255:
        raise EscrowError(f"n ({n_shares}) max 255 (1-byte index)")

    # Per byte of secret, random polynomial degree threshold-1.
    polynomials: list[list[int]] = []
    for byte_val in secret:
        coeffs = [byte_val] + [secrets.randbelow(256) for _ in range(threshold - 1)]
        polynomials.append(coeffs)

    shares: list[bytes] = []
    for idx in range(1, n_shares + 1):
        values = bytearray()
        for coeffs in polynomials:
            # Evaluate polynomial at x=idx via Horner's method.
            acc = 0
            for c in reversed(coeffs):
                acc = _gf_mul(acc, idx) ^ c
            values.append(acc)
        body = bytes([idx]) + bytes(values)
        share_hmac = _share_hmac(body)
        shares.append(body + share_hmac)
    return shares


def combine_shares(shares: list[bytes]) -> bytes:
    """Combine ≥threshold shares → original secret.

    Validates each share's HMAC + uniqueness of indices. Raises EscrowError
    при typo'е, повторе индекса, или mismatched share length.
    """
    if len(shares) < 2:
        raise EscrowError("Need at least 2 shares to combine")
    parsed: list[tuple[int, bytes]] = []
    expected_value_len: int | None = None
    seen_indices: set[int] = set()
    for share in shares:
        if len(share) < 1 + HMAC_BYTES + 1:
            raise EscrowError(f"Share too short: {len(share)} bytes")
        body, suffix = share[:-HMAC_BYTES], share[-HMAC_BYTES:]
        expected = _share_hmac(body)
        if not hmac.compare_digest(expected, suffix):
            raise EscrowError("Share HMAC mismatch — typo or corruption")
        idx = body[0]
        values = body[1:]
        if idx == 0:
            raise EscrowError("Share index 0 reserved")
        if idx in seen_indices:
            raise EscrowError(f"Duplicate share index {idx}")
        seen_indices.add(idx)
        if expected_value_len is None:
            expected_value_len = len(values)
        elif len(values) != expected_value_len:
            raise EscrowError("Shares have inconsistent length")
        parsed.append((idx, values))

    assert expected_value_len is not None
    secret = bytearray()
    for byte_pos in range(expected_value_len):
        secret.append(_lagrange_at_zero([(idx, vals[byte_pos]) for idx, vals in parsed]))
    return bytes(secret)


def _lagrange_at_zero(points: list[tuple[int, int]]) -> int:
    """Lagrange interpolation at x=0: f(0) = Σ y_i · Π (x_j / (x_j - x_i))."""
    result = 0
    for i, (xi, yi) in enumerate(points):
        # L_i(0) = Π over j≠i: (0 - x_j) / (x_i - x_j) = Π: x_j / (x_i - x_j)
        # In GF(2^8), subtraction == XOR; same as addition.
        num = 1
        denom = 1
        for j, (xj, _) in enumerate(points):
            if i == j:
                continue
            num = _gf_mul(num, xj)
            denom = _gf_mul(denom, xi ^ xj)
        term = _gf_mul(yi, _gf_mul(num, _gf_inv(denom)))
        result ^= term
    return result


def _share_hmac(body: bytes) -> bytes:
    """Truncated HMAC-SHA256 — typo detection only, not crypto auth.

    Key = domain-separation tag (public); это integrity, не secrecy.
    """
    full = hmac.new(_HMAC_TAG, body, sha256).digest()
    return full[:HMAC_BYTES]


def share_to_base32(share: bytes) -> str:
    """Encode share как human-typable base32 string (для печати на envelope).

    Base32 — case-insensitive, no ambiguous chars (0/O, 1/I) при ручном
    наборе. Length = ⌈len(share) * 8 / 5⌉; для 32-byte secret share:
    1 (idx) + 32 (vals) + 8 (hmac) = 41 bytes → 66 base32 chars (с padding).
    """
    return base64.b32encode(share).decode("ascii").rstrip("=")


def base32_to_share(s: str) -> bytes:
    """Inverse of `share_to_base32`. Tolerant к пробелам / case (human input)."""
    cleaned = "".join(s.upper().split())
    padding = "=" * (-len(cleaned) % 8)
    try:
        return base64.b32decode(cleaned + padding, casefold=True)
    except Exception as exc:
        raise EscrowError(f"Invalid base32 share: {exc}") from exc


__all__ = [
    "HMAC_BYTES",
    "SECRET_BYTES",
    "EscrowError",
    "base32_to_share",
    "combine_shares",
    "share_to_base32",
    "split_secret",
]

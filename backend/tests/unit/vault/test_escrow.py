"""Unit tests для Shamir Secret Sharing implementation (ADR-0021 A)."""

from __future__ import annotations

import secrets

import pytest

from src.api.vault.escrow import (
    HMAC_BYTES,
    SECRET_BYTES,
    EscrowError,
    base32_to_share,
    combine_shares,
    share_to_base32,
    split_secret,
)

# ---------------------------------------------------------------------------
# split + combine roundtrip


def test_split_combine_2of2_roundtrip() -> None:
    secret = secrets.token_bytes(SECRET_BYTES)
    shares = split_secret(secret, threshold=2)
    assert len(shares) == 2
    assert combine_shares(shares) == secret


def test_split_combine_3of5_roundtrip() -> None:
    """Variant B compatibility — combine любых 3 из 5."""
    secret = secrets.token_bytes(SECRET_BYTES)
    shares = split_secret(secret, threshold=3, n=5)
    assert len(shares) == 5
    # Try several 3-share subsets.
    for subset in ([0, 1, 2], [0, 2, 4], [1, 3, 4], [2, 3, 4]):
        chosen = [shares[i] for i in subset]
        assert combine_shares(chosen) == secret


def test_split_combine_small_secret() -> None:
    """Single byte secret — edge of polynomial degree."""
    shares = split_secret(b"\xab", threshold=2)
    assert combine_shares(shares) == b"\xab"


def test_split_combine_arbitrary_size() -> None:
    for size in (1, 7, 16, 32, 64, 128):
        secret = secrets.token_bytes(size)
        shares = split_secret(secret, threshold=2)
        assert combine_shares(shares) == secret


# ---------------------------------------------------------------------------
# split validation


def test_split_rejects_threshold_below_2() -> None:
    with pytest.raises(EscrowError, match="Threshold must be ≥2"):
        split_secret(b"\x00", threshold=1)


def test_split_rejects_n_below_threshold() -> None:
    with pytest.raises(EscrowError, match="must be ≥ threshold"):
        split_secret(b"\x00", threshold=3, n=2)


def test_split_rejects_n_over_255() -> None:
    with pytest.raises(EscrowError, match="max 255"):
        split_secret(b"\x00", threshold=2, n=256)


# ---------------------------------------------------------------------------
# combine validation — typo / corruption detection


def test_combine_rejects_single_share() -> None:
    secret = secrets.token_bytes(SECRET_BYTES)
    shares = split_secret(secret, threshold=2)
    with pytest.raises(EscrowError, match="at least 2 shares"):
        combine_shares([shares[0]])


def test_combine_rejects_share_with_corrupted_hmac() -> None:
    """Flipped HMAC byte → detected via integrity check."""
    secret = secrets.token_bytes(SECRET_BYTES)
    shares = split_secret(secret, threshold=2)
    corrupted = bytearray(shares[0])
    corrupted[-1] ^= 0x01  # Flip last bit of HMAC suffix.
    with pytest.raises(EscrowError, match="HMAC mismatch"):
        combine_shares([bytes(corrupted), shares[1]])


def test_combine_rejects_duplicate_indices() -> None:
    """Two shares с одинаковым index — likely user error (одну дважды ввели)."""
    secret = secrets.token_bytes(SECRET_BYTES)
    shares = split_secret(secret, threshold=2)
    with pytest.raises(EscrowError, match="Duplicate share index"):
        combine_shares([shares[0], shares[0]])


def test_combine_rejects_inconsistent_share_lengths() -> None:
    """Shares from разных secrets имеют разные value lengths."""
    s1 = split_secret(b"\x01\x02\x03", threshold=2)
    s2 = split_secret(b"\x01\x02", threshold=2)
    # Take share idx=1 от s1 + share idx=2 от s2 — both valid HMAC, but
    # value length mismatch.
    with pytest.raises(EscrowError, match="inconsistent length"):
        combine_shares([s1[0], s2[1]])


def test_combine_rejects_too_short_share() -> None:
    with pytest.raises(EscrowError, match="Share too short"):
        combine_shares([b"\x01\x02", b"\x01\x02"])


# ---------------------------------------------------------------------------
# Share encoding (base32 для печати на envelopes)


def test_share_base32_roundtrip() -> None:
    secret = secrets.token_bytes(SECRET_BYTES)
    shares = split_secret(secret, threshold=2)
    for s in shares:
        encoded = share_to_base32(s)
        assert encoded.isupper() or encoded.isalnum()
        # Base32 chars only.
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in encoded)
        assert base32_to_share(encoded) == s


def test_share_base32_tolerates_whitespace_and_case() -> None:
    """Human input может содержать пробелы / lowercase — should decode."""
    secret = secrets.token_bytes(SECRET_BYTES)
    shares = split_secret(secret, threshold=2)
    encoded = share_to_base32(shares[0])
    # Add whitespace + mixed case.
    messy = " ".join(encoded[i : i + 4].lower() for i in range(0, len(encoded), 4))
    assert base32_to_share(messy) == shares[0]


def test_base32_to_share_rejects_garbage() -> None:
    with pytest.raises(EscrowError, match="Invalid base32"):
        base32_to_share("@@@invalid@@@")


# ---------------------------------------------------------------------------
# Share format sanity


def test_share_has_expected_length() -> None:
    """1B index + N values + 8B HMAC."""
    secret = b"\xaa" * 32
    shares = split_secret(secret, threshold=2)
    for s in shares:
        assert len(s) == 1 + 32 + HMAC_BYTES


def test_share_indices_are_sequential() -> None:
    """Shares numbered 1..n."""
    shares = split_secret(b"\x00\x01", threshold=2, n=3)
    indices = [s[0] for s in shares]
    assert indices == [1, 2, 3]

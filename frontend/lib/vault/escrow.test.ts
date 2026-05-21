import { describe, expect, it } from "vitest";

import {
  EscrowError,
  SECRET_BYTES,
  base32ToShare,
  combineShares,
  shareToBase32,
  splitSecret,
} from "./escrow";

function randomBytes(n: number): Uint8Array {
  const b = new Uint8Array(n);
  crypto.getRandomValues(b);
  return b;
}

describe("Shamir SSS split/combine", () => {
  it("2-of-2 roundtrip 32 bytes (Variant A)", async () => {
    const secret = randomBytes(SECRET_BYTES);
    const shares = await splitSecret(secret);
    expect(shares).toHaveLength(2);
    const recovered = await combineShares(shares);
    expect(Array.from(recovered)).toEqual(Array.from(secret));
  });

  it("3-of-5 roundtrip любые 3 (Variant B future)", async () => {
    const secret = randomBytes(SECRET_BYTES);
    const shares = await splitSecret(secret, { threshold: 3, n: 5 });
    expect(shares).toHaveLength(5);
    for (const subset of [
      [0, 1, 2],
      [0, 2, 4],
      [1, 3, 4],
    ]) {
      const chosen = subset.map((i) => shares[i]);
      const recovered = await combineShares(chosen);
      expect(Array.from(recovered)).toEqual(Array.from(secret));
    }
  });

  it("various sizes 1/7/16/32/64", async () => {
    for (const size of [1, 7, 16, 32, 64]) {
      const secret = randomBytes(size);
      const shares = await splitSecret(secret);
      const recovered = await combineShares(shares);
      expect(Array.from(recovered)).toEqual(Array.from(secret));
    }
  });

  it("rejects threshold < 2", async () => {
    await expect(splitSecret(new Uint8Array([1]), { threshold: 1 })).rejects.toThrow(
      EscrowError,
    );
  });

  it("rejects n < threshold", async () => {
    await expect(
      splitSecret(new Uint8Array([1]), { threshold: 3, n: 2 }),
    ).rejects.toThrow(/≥ threshold/);
  });
});

describe("combine validation", () => {
  it("rejects single share", async () => {
    const shares = await splitSecret(randomBytes(SECRET_BYTES));
    await expect(combineShares([shares[0]])).rejects.toThrow(/at least 2/);
  });

  it("detects corrupted HMAC suffix", async () => {
    const shares = await splitSecret(randomBytes(SECRET_BYTES));
    const corrupted = new Uint8Array(shares[0]);
    corrupted[corrupted.length - 1] ^= 0x01;
    await expect(combineShares([corrupted, shares[1]])).rejects.toThrow(/HMAC mismatch/);
  });

  it("rejects duplicate indices", async () => {
    const shares = await splitSecret(randomBytes(SECRET_BYTES));
    await expect(combineShares([shares[0], shares[0]])).rejects.toThrow(/Duplicate/);
  });

  it("rejects inconsistent lengths", async () => {
    const a = await splitSecret(new Uint8Array([1, 2, 3]));
    const b = await splitSecret(new Uint8Array([4, 5]));
    await expect(combineShares([a[0], b[1]])).rejects.toThrow(/inconsistent/);
  });

  it("rejects too-short share", async () => {
    await expect(combineShares([new Uint8Array([1, 2]), new Uint8Array([1, 2])])).rejects.toThrow(
      /too short/,
    );
  });
});

describe("base32 encoding", () => {
  it("roundtrip", async () => {
    const shares = await splitSecret(randomBytes(SECRET_BYTES));
    for (const s of shares) {
      const encoded = shareToBase32(s);
      expect(encoded).toMatch(/^[A-Z2-7]+$/);
      const decoded = base32ToShare(encoded);
      expect(Array.from(decoded)).toEqual(Array.from(s));
    }
  });

  it("tolerant к whitespace + lowercase", async () => {
    const shares = await splitSecret(randomBytes(SECRET_BYTES));
    const encoded = shareToBase32(shares[0]);
    // Insert spaces every 4 chars + lowercase.
    const messy = encoded
      .toLowerCase()
      .match(/.{1,4}/g)!
      .join(" ");
    const decoded = base32ToShare(messy);
    expect(Array.from(decoded)).toEqual(Array.from(shares[0]));
  });

  it("rejects garbage", () => {
    expect(() => base32ToShare("@@@invalid")).toThrow(/Invalid base32/);
  });

  it("rejects empty input", () => {
    expect(() => base32ToShare("   ")).toThrow(/Empty/);
  });
});

describe("cross-impl compat (lock format)", () => {
  it("share length = 1 (idx) + N (vals) + 8 (hmac)", async () => {
    const shares = await splitSecret(new Uint8Array(32));
    expect(shares[0].length).toBe(1 + 32 + 8);
  });

  it("indices sequential 1..n", async () => {
    const shares = await splitSecret(new Uint8Array(2), { threshold: 2, n: 3 });
    expect(shares.map((s) => s[0])).toEqual([1, 2, 3]);
  });

  /**
   * Golden vector generated via `backend/src/api/vault/escrow.py` с
   * monkey-patched `secrets.randbelow → random.randint(0, n-1)` под
   * `random.seed(42)`. Lock-test cross-impl format compatibility:
   * Python-generated shares decode + combine в TS → original secret.
   *
   * Если этот тест fail'ит — либо HMAC tag сместился, либо GF math
   * расходится, либо base32 format ломается. Любая из трёх ситуаций
   * блокирует emergency recovery в production.
   */
  it("combines Python-generated shares back to original secret", async () => {
    const SECRET_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
    const SHARE1_B32 = "AE4Q3DT6OZBDEK6QDECSIY32ANVMMYPXTULUJTVZSZLHJNZIGLOC5AFSYCMBBJ6LSU";
    const SHARE2_B32 = "AJZBSAPZ4CFW4X5DFEKFLUXDCTC2P4ODCQJLPPKQD6D4MWDUIOAX2QSJH7QDDTNBPI";

    const share1 = base32ToShare(SHARE1_B32);
    const share2 = base32ToShare(SHARE2_B32);
    const recovered = await combineShares([share1, share2]);

    const expected = new Uint8Array(SECRET_HEX.match(/.{2}/g)!.map((h) => parseInt(h, 16)));
    expect(Array.from(recovered)).toEqual(Array.from(expected));
  });
});

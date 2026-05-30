/**
 * TOTP RFC 6238 tests.
 *
 * KAT vectors per RFC 6238 §Appendix B (SHA1 algorithm, 8-digit codes
 * vs наш 6-digit вариант — codes consistent через `% 1e6`).
 *
 * Test secret: ASCII "12345678901234567890" — 20 bytes, hex
 * `3132333435363738393031323334353637383930`.
 */

import { describe, expect, it } from "vitest";

import {
  base32Decode,
  base32Encode,
  generateTotpSecret,
  otpauthQrDataUrl,
  otpauthUri,
  totpCode,
  verifyTotpCode,
} from "./totp";

const RFC_SECRET = new TextEncoder().encode("12345678901234567890");

describe("base32 encode/decode", () => {
  it("round-trip empty", () => {
    expect(base32Decode(base32Encode(new Uint8Array()))).toEqual(
      new Uint8Array(),
    );
  });

  it("round-trip random data", () => {
    const data = new Uint8Array([0, 1, 2, 200, 255, 100]);
    expect(base32Decode(base32Encode(data))).toEqual(data);
  });

  it("decodes RFC 4648 example (lowercase + spaces tolerant)", () => {
    // ASCII 'foobar' = 'MZXW6YTBOI======' canonical (with padding).
    const decoded = base32Decode("MZXW6YTBOI======");
    expect(new TextDecoder().decode(decoded)).toBe("foobar");
    // Случайные пробелы и lowercase ignored.
    expect(new TextDecoder().decode(base32Decode("mz xw 6yT BoI"))).toBe(
      "foobar",
    );
  });

  it("encode produces canonical RFC 4648 (no padding в нашем варианте)", () => {
    expect(base32Encode(new TextEncoder().encode("foobar"))).toBe("MZXW6YTBOI");
  });

  it("rejects invalid chars", () => {
    expect(() => base32Decode("1@!")).toThrow(/invalid char/);
  });
});

describe("generateTotpSecret", () => {
  it("produces 20-byte non-zero secret", () => {
    const s = generateTotpSecret();
    expect(s.length).toBe(20);
    expect(s.some((b) => b !== 0)).toBe(true);
  });
});

describe("otpauthUri", () => {
  it("includes secret + issuer + algorithm + digits + period", () => {
    const uri = otpauthUri(RFC_SECRET, "alice@example.com", "reHome");
    expect(uri).toMatch(/^otpauth:\/\/totp\/alice/);
    expect(uri).toMatch(/secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ/);
    expect(uri).toContain("issuer=reHome");
    expect(uri).toContain("algorithm=SHA1");
    expect(uri).toContain("digits=6");
    expect(uri).toContain("period=30");
  });
});

describe("totpCode RFC 6238 KAT vectors", () => {
  // RFC 6238 Appendix B test vectors (SHA1 column). Каждая строка:
  // [unix_seconds, expected_8_digit_code]. Наш 6-digit берёт last 6.
  const KAT: [number, string][] = [
    [59, "94287082"],
    [1111111109, "07081804"],
    [1111111111, "14050471"],
    [1234567890, "89005924"],
    [2000000000, "69279037"],
    [20000000000, "65353130"],
  ];

  for (const [ts, code8] of KAT) {
    it(`t=${ts} → last 6 of ${code8}`, async () => {
      const ours = await totpCode(RFC_SECRET, ts);
      expect(ours).toBe(code8.slice(-6));
    });
  }
});

describe("verifyTotpCode", () => {
  it("accepts current step code", async () => {
    const now = Math.floor(Date.now() / 1000);
    const code = await totpCode(RFC_SECRET, now);
    expect(await verifyTotpCode(RFC_SECRET, code)).toBe(true);
  });

  it("accepts ±1 step drift", async () => {
    const now = Math.floor(Date.now() / 1000);
    const prevCode = await totpCode(RFC_SECRET, now - 30);
    const nextCode = await totpCode(RFC_SECRET, now + 30);
    expect(await verifyTotpCode(RFC_SECRET, prevCode)).toBe(true);
    expect(await verifyTotpCode(RFC_SECRET, nextCode)).toBe(true);
  });

  it("rejects out-of-window code (3 steps ago)", async () => {
    const past = await totpCode(RFC_SECRET, Math.floor(Date.now() / 1000) - 120);
    expect(await verifyTotpCode(RFC_SECRET, past)).toBe(false);
  });

  it("rejects non-6-digit input", async () => {
    expect(await verifyTotpCode(RFC_SECRET, "12345")).toBe(false);
    expect(await verifyTotpCode(RFC_SECRET, "1234567")).toBe(false);
    expect(await verifyTotpCode(RFC_SECRET, "abcdef")).toBe(false);
    expect(await verifyTotpCode(RFC_SECRET, "")).toBe(false);
  });

  it("tolerates whitespace в user input", async () => {
    const now = Math.floor(Date.now() / 1000);
    const code = await totpCode(RFC_SECRET, now);
    const spaced = `${code.slice(0, 3)} ${code.slice(3)}`;
    expect(await verifyTotpCode(RFC_SECRET, spaced)).toBe(true);
  });

  it("rejects wrong code", async () => {
    expect(await verifyTotpCode(RFC_SECRET, "000000")).toBe(false);
  });
});

describe("otpauthQrDataUrl", () => {
  it("returns PNG data URL для valid otpauth URI", async () => {
    const uri = otpauthUri(RFC_SECRET, "alice", "reHome Vault");
    const dataUrl = await otpauthQrDataUrl(uri);
    expect(dataUrl).toMatch(/^data:image\/png;base64,/);
    // Base64-payload должен быть нетривиальным (QR с ~33 модулей → kb-sized image).
    expect(dataUrl.length).toBeGreaterThan(200);
  });

  it("throws при empty URI", async () => {
    await expect(otpauthQrDataUrl("")).rejects.toThrow(/empty uri/);
  });
});

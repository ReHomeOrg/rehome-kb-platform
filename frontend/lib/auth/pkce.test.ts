/**
 * Tests for PKCE helpers (RFC 7636).
 */
import { describe, it, expect } from "vitest";

import {
  base64UrlEncode,
  computeCodeChallengeS256,
  generateCodeVerifier,
} from "./pkce";

describe("generateCodeVerifier", () => {
  it("returns a string between 43 and 128 chars (RFC 7636 §4.1)", () => {
    const verifier = generateCodeVerifier();
    expect(verifier.length).toBeGreaterThanOrEqual(43);
    expect(verifier.length).toBeLessThanOrEqual(128);
  });

  it("returns only base64url charset characters [A-Z a-z 0-9 - _]", () => {
    const verifier = generateCodeVerifier();
    expect(verifier).toMatch(/^[A-Za-z0-9\-_]+$/);
  });

  it("produces unique values across iterations (no collisions)", () => {
    const set = new Set<string>();
    for (let i = 0; i < 1000; i++) {
      set.add(generateCodeVerifier());
    }
    expect(set.size).toBe(1000);
  });
});

describe("computeCodeChallengeS256", () => {
  it("matches RFC 7636 Appendix B test vector", async () => {
    // RFC 7636 Appendix B:
    //   code_verifier  = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    //   code_challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    const challenge = await computeCodeChallengeS256(verifier);
    expect(challenge).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  it("produces 43-char base64url-encoded SHA-256 hash", async () => {
    const challenge = await computeCodeChallengeS256("any-verifier");
    expect(challenge).toMatch(/^[A-Za-z0-9\-_]+$/);
    expect(challenge.length).toBe(43); // 256/6 = 42.67 → 43 chars without padding
  });
});

describe("base64UrlEncode", () => {
  it("replaces + with -, / with _, removes padding", () => {
    // Bytes that would produce + or / in standard base64.
    const bytes = new Uint8Array([0xfb, 0xff, 0xff]); // base64: "+///"
    const encoded = base64UrlEncode(bytes);
    expect(encoded).not.toContain("+");
    expect(encoded).not.toContain("/");
    expect(encoded).not.toContain("=");
    expect(encoded).toBe("-___");
  });
});

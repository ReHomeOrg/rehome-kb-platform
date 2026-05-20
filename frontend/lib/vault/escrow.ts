/**
 * Shamir Secret Sharing over GF(256) — emergency access (ADR-0021 A).
 *
 * TypeScript port of `backend/src/api/vault/escrow.py`. Same algorithm:
 * polynomial per byte, Lagrange interpolation at x=0, HMAC-SHA256
 * truncated to 8 bytes for typo detection. Same `share_to_base32` format
 * → backend Python decoder accepts client-side encoded shares и наоборот.
 *
 * Per ADR §approve note «zero-knowledge preserved»: combine + decrypt
 * happen client-side; backend никогда не видит shares.
 */

const HMAC_BYTES = 8;
const HMAC_TAG = "rehome.vault.escrow.share.hmac.v1";
const BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

export const SECRET_BYTES = 32;

export class EscrowError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EscrowError";
  }
}

// ---------------------------------------------------------------------------
// GF(256) arithmetic — Rijndael field.

function gfMul(a: number, b: number): number {
  let p = 0;
  for (let i = 0; i < 8; i++) {
    if (b & 1) p ^= a;
    b >>= 1;
    const carry = a & 0x80;
    a = (a << 1) & 0xff;
    if (carry) a ^= 0x1b;
  }
  return p;
}

function gfInv(a: number): number {
  if (a === 0) throw new EscrowError("Division by zero in GF(256)");
  for (let x = 1; x < 256; x++) {
    if (gfMul(a, x) === 1) return x;
  }
  throw new EscrowError("Inverse not found");
}

// ---------------------------------------------------------------------------
// HMAC suffix — typo detection.

async function shareHmac(body: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(HMAC_TAG),
    { name: "HMAC", hash: "SHA-256" },
    /* extractable */ false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, body as BufferSource);
  return new Uint8Array(sig).slice(0, HMAC_BYTES);
}

function constantTimeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

// ---------------------------------------------------------------------------
// split + combine

export interface SplitOptions {
  threshold?: number;
  n?: number;
}

/**
 * Split `secret` into n shares; любые `threshold` recover'ят. Default
 * 2-of-2 (Variant A).
 *
 * Each share = `[index 1B][values len(secret) B][hmac 8B]`. Indices 1..n.
 */
export async function splitSecret(
  secret: Uint8Array,
  options: SplitOptions = {},
): Promise<Uint8Array[]> {
  const threshold = options.threshold ?? 2;
  const nShares = options.n ?? threshold;
  if (threshold < 2) {
    throw new EscrowError(`Threshold must be ≥2, got ${threshold}`);
  }
  if (nShares < threshold) {
    throw new EscrowError(`n (${nShares}) must be ≥ threshold (${threshold})`);
  }
  if (nShares > 255) {
    throw new EscrowError(`n (${nShares}) max 255 (1-byte index)`);
  }

  const polynomials: number[][] = [];
  const randomCoeffs = new Uint8Array(secret.length * (threshold - 1));
  crypto.getRandomValues(randomCoeffs);
  for (let i = 0; i < secret.length; i++) {
    const coeffs = [secret[i]];
    for (let j = 0; j < threshold - 1; j++) {
      coeffs.push(randomCoeffs[i * (threshold - 1) + j]);
    }
    polynomials.push(coeffs);
  }

  const shares: Uint8Array[] = [];
  for (let idx = 1; idx <= nShares; idx++) {
    const values = new Uint8Array(secret.length);
    for (let p = 0; p < polynomials.length; p++) {
      const coeffs = polynomials[p];
      let acc = 0;
      // Horner evaluation at x=idx in reverse.
      for (let c = coeffs.length - 1; c >= 0; c--) {
        acc = gfMul(acc, idx) ^ coeffs[c];
      }
      values[p] = acc;
    }
    const body = new Uint8Array(1 + values.length);
    body[0] = idx;
    body.set(values, 1);
    const hmac = await shareHmac(body);
    const share = new Uint8Array(body.length + hmac.length);
    share.set(body);
    share.set(hmac, body.length);
    shares.push(share);
  }
  return shares;
}

function lagrangeAtZero(points: Array<[number, number]>): number {
  let result = 0;
  for (let i = 0; i < points.length; i++) {
    const [xi, yi] = points[i];
    let num = 1;
    let denom = 1;
    for (let j = 0; j < points.length; j++) {
      if (i === j) continue;
      const xj = points[j][0];
      num = gfMul(num, xj);
      denom = gfMul(denom, xi ^ xj);
    }
    const term = gfMul(yi, gfMul(num, gfInv(denom)));
    result ^= term;
  }
  return result;
}

/**
 * Combine ≥2 shares → original secret. Validates HMAC + index uniqueness
 * + length consistency. Throws EscrowError на typo / corruption.
 */
export async function combineShares(shares: Uint8Array[]): Promise<Uint8Array> {
  if (shares.length < 2) {
    throw new EscrowError("Need at least 2 shares to combine");
  }
  const parsed: Array<[number, Uint8Array]> = [];
  let expectedLen: number | null = null;
  const seenIndices = new Set<number>();
  for (const share of shares) {
    if (share.length < 1 + HMAC_BYTES + 1) {
      throw new EscrowError(`Share too short: ${share.length} bytes`);
    }
    const body = share.slice(0, share.length - HMAC_BYTES);
    const suffix = share.slice(share.length - HMAC_BYTES);
    const expected = await shareHmac(body);
    if (!constantTimeEqual(expected, suffix)) {
      throw new EscrowError("Share HMAC mismatch — typo or corruption");
    }
    const idx = body[0];
    const values = body.slice(1);
    if (idx === 0) throw new EscrowError("Share index 0 reserved");
    if (seenIndices.has(idx)) {
      throw new EscrowError(`Duplicate share index ${idx}`);
    }
    seenIndices.add(idx);
    if (expectedLen === null) {
      expectedLen = values.length;
    } else if (values.length !== expectedLen) {
      throw new EscrowError("Shares have inconsistent length");
    }
    parsed.push([idx, values]);
  }
  if (expectedLen === null) {
    throw new EscrowError("No valid shares");
  }
  const secret = new Uint8Array(expectedLen);
  for (let pos = 0; pos < expectedLen; pos++) {
    const points: Array<[number, number]> = parsed.map(([idx, vals]) => [idx, vals[pos]]);
    secret[pos] = lagrangeAtZero(points);
  }
  return secret;
}

// ---------------------------------------------------------------------------
// Base32 encoding для человеко-вводимых envelope strings.

export function shareToBase32(share: Uint8Array): string {
  // RFC 4648 base32 без padding, для совместимости с Python's
  // base64.b32encode().rstrip('=').
  let bits = 0;
  let value = 0;
  let output = "";
  for (let i = 0; i < share.length; i++) {
    value = (value << 8) | share[i];
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      output += BASE32_ALPHABET[(value >>> bits) & 0x1f];
    }
  }
  if (bits > 0) {
    output += BASE32_ALPHABET[(value << (5 - bits)) & 0x1f];
  }
  return output;
}

export function base32ToShare(s: string): Uint8Array {
  // Tolerant к whitespace / lowercase (human input).
  const cleaned = s.replace(/\s+/g, "").toUpperCase();
  if (!cleaned) throw new EscrowError("Empty base32 input");
  if (!/^[A-Z2-7]+$/.test(cleaned)) {
    throw new EscrowError("Invalid base32 share (illegal characters)");
  }
  const out: number[] = [];
  let bits = 0;
  let value = 0;
  for (const ch of cleaned) {
    const idx = BASE32_ALPHABET.indexOf(ch);
    if (idx < 0) throw new EscrowError(`Invalid base32 char: ${ch}`);
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      out.push((value >>> bits) & 0xff);
    }
  }
  return new Uint8Array(out);
}

/**
 * TOTP RFC 6238 helpers для kb-vault Slice 4.
 *
 * Pure WebCrypto + base32 — no external dependencies.
 *
 * Параметры:
 * - Algorithm: HMAC-SHA1 (RFC 6238 default; совместимо с Google
 *   Authenticator / FreeOTP / Aegis / Yandex Key).
 * - Digits: 6.
 * - Step: 30 seconds.
 * - Secret length: 20 bytes (160 bits) per RFC 4226 §4 recommendation.
 *
 * Zero-knowledge integration: TOTP secret generated клиентом, encrypted
 * под vaultKey AES-GCM, передаётся на сервер как opaque blob. Server
 * НЕ может derive codes / verify.
 *
 * Verify flow на unlock:
 * 1. Decrypt totp_secret_encrypted_b64 vaultKey'ом.
 * 2. Compute expected code локально для current/prev/next time-step
 *    (±30sec drift allowance).
 * 3. Compare с user-entered code. Pass → submit auth_hash на /unlock.
 */

import QRCode from "qrcode";

import { randomBytes } from "./crypto";

const TOTP_DIGITS = 6;
const TOTP_STEP_SECONDS = 30;
const TOTP_SECRET_BYTES = 20;

// RFC 4648 Base32 alphabet (без padding на encode для TOTP, padding на decode).
const BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/** Encode bytes → RFC 4648 base32 (без padding). */
export function base32Encode(bytes: Uint8Array): string {
  let bits = 0;
  let value = 0;
  let output = "";
  for (let i = 0; i < bytes.length; i++) {
    value = (value << 8) | bytes[i]!;
    bits += 8;
    while (bits >= 5) {
      output += BASE32_ALPHABET[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  if (bits > 0) {
    output += BASE32_ALPHABET[(value << (5 - bits)) & 31];
  }
  return output;
}

/** Decode base32 string → bytes. Ignores padding and case. */
export function base32Decode(s: string): Uint8Array {
  const cleaned = s.toUpperCase().replace(/=+$/, "").replace(/\s/g, "");
  let bits = 0;
  let value = 0;
  const output: number[] = [];
  for (const ch of cleaned) {
    const idx = BASE32_ALPHABET.indexOf(ch);
    if (idx === -1) {
      throw new Error(`base32: invalid char ${ch}`);
    }
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      output.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return new Uint8Array(output);
}

/** Generate random TOTP secret (20 bytes per RFC 4226 §4). */
export function generateTotpSecret(): Uint8Array {
  return randomBytes(TOTP_SECRET_BYTES);
}

/** Build otpauth:// URI (RFC 6238 + Google Authenticator extensions).
 * `label` обычно `account@issuer`; `issuer` дублируется в query для
 * Yandex/Authy compat. */
export function otpauthUri(secret: Uint8Array, label: string, issuer: string): string {
  const params = new URLSearchParams();
  params.set("secret", base32Encode(secret));
  params.set("issuer", issuer);
  params.set("algorithm", "SHA1");
  params.set("digits", String(TOTP_DIGITS));
  params.set("period", String(TOTP_STEP_SECONDS));
  return `otpauth://totp/${encodeURIComponent(label)}?${params.toString()}`;
}

/**
 * Render otpauth URI as PNG data URL для embedding в `<img src>`.
 *
 * Параметры QR кодирования:
 * - `errorCorrectionLevel: 'M'` (15% recovery) — стандарт otpauth,
 *   достаточно для печатного / экранного скана камерой телефона.
 * - `margin: 1` — минимальная quiet zone (модули). 0 ломает scan'инг
 *   у некоторых scanner'ов; 4 (default) визуально избыточен в форме.
 * - `scale: 4` — 4 px на модуль; для otpauth URI типичный QR ~33
 *   модуля → ~132 px image, хорошо помещается в форму setup wizard'а.
 *
 * Wrapper нужен по двум причинам: (а) центральная конфигурация QR
 * params, (б) тестируемость — UI компоненты мокают эту функцию вместо
 * вытягивания `qrcode` lib в jsdom.
 *
 * `uri` пустой → throw — caller обязан передавать готовый otpauth URI.
 */
export async function otpauthQrDataUrl(uri: string): Promise<string> {
  if (!uri) {
    throw new Error("otpauthQrDataUrl: empty uri");
  }
  return QRCode.toDataURL(uri, {
    errorCorrectionLevel: "M",
    margin: 1,
    scale: 4,
  });
}

/**
 * Compute TOTP code for a given timestamp.
 *
 * `timestamp` — Unix seconds. Caller передаёт `Date.now()/1000` для
 * текущего; ±30 для drift allowance в `verifyTotpCode`.
 */
export async function totpCode(
  secret: Uint8Array,
  timestamp: number,
): Promise<string> {
  // 8-byte big-endian counter. JavaScript bitwise — 32-bit, но counter
  // < 2^32 до ~2106 года (timestamp 2^32 * 30sec ~ 4127 года), поэтому
  // simple division loop работает без BigInt.
  let counter = Math.floor(timestamp / TOTP_STEP_SECONDS);
  const counterBytes = new Uint8Array(8);
  for (let i = 7; i >= 0; i--) {
    counterBytes[i] = counter & 0xff;
    counter = Math.floor(counter / 256);
  }

  const hmacKey = await crypto.subtle.importKey(
    "raw",
    secret as unknown as BufferSource,
    { name: "HMAC", hash: "SHA-1" },
    false,
    ["sign"],
  );
  const sigBuf = await crypto.subtle.sign(
    "HMAC",
    hmacKey,
    counterBytes as unknown as BufferSource,
  );
  const sig = new Uint8Array(sigBuf);
  // Dynamic truncation per RFC 4226 §5.3.
  const offset = sig[sig.length - 1]! & 0x0f;
  const truncated =
    ((sig[offset]! & 0x7f) << 24) |
    ((sig[offset + 1]! & 0xff) << 16) |
    ((sig[offset + 2]! & 0xff) << 8) |
    (sig[offset + 3]! & 0xff);
  const code = (truncated % 10 ** TOTP_DIGITS).toString();
  return code.padStart(TOTP_DIGITS, "0");
}

/**
 * Verify user-entered code against secret. Allows ±1 step drift (30 sec
 * either side) per RFC 6238 §6 recommendation.
 *
 * Constant-time compare НЕ нужен здесь — TOTP is short-lived и в случае
 * brute-force ratelimited offline. Все же используем char-wise compare
 * для defense-in-depth.
 */
export async function verifyTotpCode(
  secret: Uint8Array,
  userCode: string,
): Promise<boolean> {
  const normalised = userCode.replace(/\s/g, "");
  if (!/^\d{6}$/.test(normalised)) {
    return false;
  }
  const now = Math.floor(Date.now() / 1000);
  for (const offset of [-TOTP_STEP_SECONDS, 0, TOTP_STEP_SECONDS]) {
    const expected = await totpCode(secret, now + offset);
    if (constantTimeEqual(expected, normalised)) {
      return true;
    }
  }
  return false;
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

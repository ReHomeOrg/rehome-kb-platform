/**
 * OAuth `state` parameter — CSRF protection.
 *
 * Криптографически случайный nonce, который привязывается к login-сессии в
 * cookie и проверяется на callback. Без него злоумышленник мог бы заставить
 * жертву залогиниться от своего имени (CSRF на OAuth flow).
 */

import { base64UrlEncode } from "./pkce";

const STATE_BYTES = 32; // 256 бит энтропии (OWASP требует ≥128)

export function generateState(): string {
  const buf = new Uint8Array(STATE_BYTES);
  crypto.getRandomValues(buf);
  return base64UrlEncode(buf);
}

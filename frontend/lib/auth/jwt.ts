/**
 * Lightweight JWT decoding (#169).
 *
 * Цель — read `exp` claim для pre-emptive refresh scheduling.
 * Сигнатуру НЕ верифицируем: cookie HttpOnly, устанавливается только
 * нашим backend callback'ом → trusted. Signature verification потребовал
 * бы Keycloak JWKS fetch — overkill для просто чтения timestamp'а.
 *
 * Returns `null` если token malformed (defensive — caller treats as
 * no-session).
 */

export interface JwtClaims {
  /** Expiration time (Unix seconds). */
  exp?: number;
  /** Issued-at (Unix seconds). */
  iat?: number;
  sub?: string;
  /** ADR-0019: step-up Authentication Context Class Reference. */
  acr?: string | number;
  /** OIDC nonce — replay-protection (must match nonce sent в `/auth`). */
  nonce?: string;
  /** Keycloak realm roles, напр. `{ roles: ["staff_admin"] }`. Только для
   * UI-видимости (скрытие кнопок) — авторизацию enforce'ит backend. */
  realm_access?: { roles?: string[] };
}

function _b64urlDecode(str: string): string | null {
  // base64url → base64 (-/_ → +//= padding restore)
  const padded = str.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4;
  const fullPadded = pad ? padded + "=".repeat(4 - pad) : padded;
  try {
    if (typeof atob === "function") {
      return atob(fullPadded);
    }
    // Node-only fallback (Server Components / route handlers).
    return Buffer.from(fullPadded, "base64").toString("utf-8");
  } catch {
    return null;
  }
}

export function decodeJwtClaims(token: string): JwtClaims | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const payload = _b64urlDecode(parts[1]);
  if (payload === null) return null;
  try {
    const claims = JSON.parse(payload) as unknown;
    if (typeof claims !== "object" || claims === null) return null;
    return claims as JwtClaims;
  } catch {
    return null;
  }
}

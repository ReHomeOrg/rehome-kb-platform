/**
 * Cookie name constants and options.
 *
 * Все auth-cookies — HttpOnly (нет доступа из JS), Secure в production,
 * SameSite=Lax (защита от CSRF на cross-origin POST'ах).
 */

export const COOKIE_SESSION = "kb_session";
export const COOKIE_PKCE_VERIFIER = "kb_pkce_verifier";
export const COOKIE_OAUTH_STATE = "kb_oauth_state";

/** TTL для коротких login-flow cookies (state, verifier) — 5 минут. */
export const SHORT_FLOW_MAX_AGE_SECONDS = 300;

export interface CookieOptions {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: "/";
  maxAge: number;
}

export function getCookieOptions(maxAgeSeconds: number): CookieOptions {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: maxAgeSeconds,
  };
}

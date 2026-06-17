/**
 * Cookie name constants and options.
 *
 * Все auth-cookies — HttpOnly (нет доступа из JS), Secure в production,
 * SameSite=Lax (защита от CSRF на cross-origin POST'ах).
 */

export const COOKIE_SESSION = "kb_session";
export const COOKIE_REFRESH = "kb_refresh";
export const COOKIE_PKCE_VERIFIER = "kb_pkce_verifier";
export const COOKIE_OAUTH_STATE = "kb_oauth_state";

/** TTL для login-flow cookies (state, PKCE verifier) — 30 минут.
 *
 * ДОЛЖНО совпадать с Keycloak `accessCodeLifespanLogin` (login timeout, 1800с).
 * Если cookie живёт меньше, чем пользователь вводит креды на странице Keycloak
 * (менеджер паролей, первый вход, MFA), то к моменту колбэка `kb_oauth_state`
 * уже истекла → проверка state падает с "Invalid state" (HTTP 400). */
export const SHORT_FLOW_MAX_AGE_SECONDS = 1800;

/** Refresh token cookie TTL — 30 дней. Keycloak default refresh expiry
 * обычно 30 дней; cookie не должна жить дольше серверного токена. */
export const REFRESH_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

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

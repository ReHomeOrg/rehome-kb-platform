/**
 * POST /api/auth/refresh (#161)
 *
 * Swap expired access_token for fresh one через refresh_token cookie.
 * Browser-side `apiFetch` дёргает этот endpoint после 401 и retry'ит
 * original request с новым cookie.
 *
 * Шаги:
 * 1. Read `kb_refresh` cookie. Если нет — 401 (caller forces re-login).
 * 2. POST к Keycloak /token (grant_type=refresh_token).
 * 3. Set new `kb_session` cookie + (опционально) rotated `kb_refresh`.
 * 4. Return 200 + JSON `{success: true}`.
 *
 * Errors:
 * - 401 если refresh cookie отсутствует или Keycloak отклонил
 *   (revoked / expired token). Caller должен redirect на /login.
 * - 502 если Keycloak unreachable.
 *
 * Метод POST (не GET) — обновление state; CSRF protection через SameSite=Lax
 * cookie (default для современных browsers).
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getAuthConfig } from "@/lib/auth/config";
import {
  COOKIE_REFRESH,
  COOKIE_SESSION,
  REFRESH_MAX_AGE_SECONDS,
  getCookieOptions,
} from "@/lib/auth/cookies";
import { refreshAccessToken } from "@/lib/auth/keycloak";

export async function POST(): Promise<NextResponse> {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(COOKIE_REFRESH)?.value;
  if (!refreshToken) {
    return NextResponse.json(
      { error: "no_refresh_token" },
      { status: 401 },
    );
  }

  const config = getAuthConfig();
  let tokens;
  try {
    tokens = await refreshAccessToken(config, refreshToken);
  } catch {
    // Refresh failed — token revoked / expired / Keycloak error.
    // 401 forces caller redirect к /login. Не logging error_description
    // (может содержать user-data).
    const failResponse = NextResponse.json(
      { error: "refresh_failed" },
      { status: 401 },
    );
    // Очищаем cookie чтобы избежать retry loop'а на dead refresh token.
    failResponse.cookies.delete(COOKIE_REFRESH);
    failResponse.cookies.delete(COOKIE_SESSION);
    return failResponse;
  }

  const response = NextResponse.json({ success: true }, { status: 200 });
  response.cookies.set(
    COOKIE_SESSION,
    tokens.access_token,
    getCookieOptions(tokens.expires_in),
  );
  // Keycloak обычно rotate'ит refresh token при каждом use'е — persist
  // новый если пришёл.
  if (tokens.refresh_token) {
    response.cookies.set(
      COOKIE_REFRESH,
      tokens.refresh_token,
      getCookieOptions(REFRESH_MAX_AGE_SECONDS),
    );
  }
  return response;
}

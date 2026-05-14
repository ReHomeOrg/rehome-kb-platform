/**
 * GET /api/auth/callback/keycloak
 *
 * OAuth Authorization Code callback. Путь точно соответствует ADR-0007
 * (`redirectUris: ["http://localhost:3000/api/auth/callback/keycloak", ...]`).
 *
 * Шаги:
 * 1. Валидируем state против cookie (защита от OAuth-CSRF)
 * 2. Достаём code_verifier из cookie
 * 3. POST /token с code + code_verifier
 * 4. Сохраняем access_token в HttpOnly cookie `kb_session`
 * 5. Чистим временные cookies (verifier + state)
 * 6. Редиректим на /
 *
 * Поведение при ошибках — 400 (Bad Request). Никогда не логируем
 * `error_description` от Keycloak (может содержать user-data).
 */

import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { getAuthConfig } from "@/lib/auth/config";
import {
  COOKIE_OAUTH_STATE,
  COOKIE_PKCE_VERIFIER,
  COOKIE_REFRESH,
  COOKIE_SESSION,
  REFRESH_MAX_AGE_SECONDS,
  getCookieOptions,
} from "@/lib/auth/cookies";
import { exchangeCodeForToken } from "@/lib/auth/keycloak";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const searchParams = request.nextUrl.searchParams;
  const code = searchParams.get("code");
  const state = searchParams.get("state");

  if (!code || !state) {
    return new NextResponse("Missing code or state", { status: 400 });
  }

  const cookieStore = await cookies();
  const expectedState = cookieStore.get(COOKIE_OAUTH_STATE)?.value;
  const codeVerifier = cookieStore.get(COOKIE_PKCE_VERIFIER)?.value;

  if (!expectedState || state !== expectedState) {
    // OAuth-CSRF: state не совпадает — это попытка атаки.
    return new NextResponse("Invalid state", { status: 400 });
  }

  if (!codeVerifier) {
    return new NextResponse("Missing PKCE verifier", { status: 400 });
  }

  const config = getAuthConfig();
  let tokens;
  try {
    tokens = await exchangeCodeForToken(config, code, codeVerifier);
  } catch {
    // Логировать без error_description (может содержать user-data).
    return new NextResponse("Token exchange failed", { status: 502 });
  }

  // Чистим временные cookies и устанавливаем session + refresh cookies.
  const response = NextResponse.redirect(new URL("/", request.url));
  response.cookies.set(
    COOKIE_SESSION,
    tokens.access_token,
    getCookieOptions(tokens.expires_in),
  );
  // Refresh token persists дольше access (Keycloak default 30 дней).
  // 401 на gated endpoint → /api/auth/refresh swap'нет access_token
  // не теряя сессию (см. #161).
  if (tokens.refresh_token) {
    response.cookies.set(
      COOKIE_REFRESH,
      tokens.refresh_token,
      getCookieOptions(REFRESH_MAX_AGE_SECONDS),
    );
  }
  response.cookies.delete(COOKIE_PKCE_VERIFIER);
  response.cookies.delete(COOKIE_OAUTH_STATE);
  return response;
}

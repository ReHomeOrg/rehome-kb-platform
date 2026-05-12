/**
 * GET /api/auth/login
 *
 * Initiates OAuth Authorization Code + PKCE flow.
 *
 * Шаги:
 * 1. Генерируем PKCE code_verifier (32 байта random)
 * 2. Считаем code_challenge = S256(code_verifier)
 * 3. Генерируем state (32 байта random, OWASP ≥128 bits)
 * 4. Сохраняем code_verifier и state в HttpOnly cookies (TTL 5 мин)
 * 5. Редиректим на Keycloak /auth с нужными query params
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getAuthConfig } from "@/lib/auth/config";
import {
  COOKIE_OAUTH_STATE,
  COOKIE_PKCE_VERIFIER,
  SHORT_FLOW_MAX_AGE_SECONDS,
  getCookieOptions,
} from "@/lib/auth/cookies";
import { buildAuthorizationUrl } from "@/lib/auth/keycloak";
import { computeCodeChallengeS256, generateCodeVerifier } from "@/lib/auth/pkce";
import { generateState } from "@/lib/auth/state";

export async function GET(): Promise<NextResponse> {
  const config = getAuthConfig();

  const codeVerifier = generateCodeVerifier();
  const codeChallenge = await computeCodeChallengeS256(codeVerifier);
  const state = generateState();

  const cookieStore = await cookies();
  const opts = getCookieOptions(SHORT_FLOW_MAX_AGE_SECONDS);
  cookieStore.set(COOKIE_PKCE_VERIFIER, codeVerifier, opts);
  cookieStore.set(COOKIE_OAUTH_STATE, state, opts);

  const authUrl = buildAuthorizationUrl(config, { state, codeChallenge });
  return NextResponse.redirect(authUrl);
}

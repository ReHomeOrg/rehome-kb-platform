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
 *
 * Необязательный query `kc_idp_hint` (brokered-login «Авторизация в rehome»)
 * пробрасывается ТОЛЬКО если входит в allowlist (`isAllowedIdpHint`) — чужой
 * hint игнорируется (анти-param-injection).
 */

import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { getAuthConfig, isAllowedIdpHint } from "@/lib/auth/config";
import {
  COOKIE_OAUTH_STATE,
  COOKIE_PKCE_VERIFIER,
  SHORT_FLOW_MAX_AGE_SECONDS,
  getCookieOptions,
} from "@/lib/auth/cookies";
import { buildAuthorizationUrl } from "@/lib/auth/keycloak";
import { computeCodeChallengeS256, generateCodeVerifier } from "@/lib/auth/pkce";
import { generateState } from "@/lib/auth/state";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const config = getAuthConfig();

  // brokered-login: пробрасываем kc_idp_hint только из allowlist (иначе undefined).
  const idpHintParam = request.nextUrl.searchParams.get("kc_idp_hint");
  const idpHint = isAllowedIdpHint(idpHintParam) ? idpHintParam : undefined;

  const codeVerifier = generateCodeVerifier();
  const codeChallenge = await computeCodeChallengeS256(codeVerifier);
  const state = generateState();

  const cookieStore = await cookies();
  const opts = getCookieOptions(SHORT_FLOW_MAX_AGE_SECONDS);
  cookieStore.set(COOKIE_PKCE_VERIFIER, codeVerifier, opts);
  cookieStore.set(COOKIE_OAUTH_STATE, state, opts);

  const authUrl = buildAuthorizationUrl(config, { state, codeChallenge, idpHint });
  return NextResponse.redirect(authUrl);
}

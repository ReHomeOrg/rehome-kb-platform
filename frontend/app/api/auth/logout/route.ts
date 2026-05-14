/**
 * POST /api/auth/logout
 *
 * Очищает session cookie и редиректит на Keycloak /logout (frontchannel).
 *
 * POST (не GET) — защита от случайного logout через ссылки/изображения.
 */

import { NextResponse } from "next/server";

import { getAuthConfig } from "@/lib/auth/config";
import { COOKIE_REFRESH, COOKIE_SESSION } from "@/lib/auth/cookies";
import { buildLogoutUrl } from "@/lib/auth/keycloak";

export function POST(): NextResponse {
  const config = getAuthConfig();
  const response = NextResponse.redirect(buildLogoutUrl(config));
  response.cookies.delete(COOKIE_SESSION);
  // Refresh token также очищаем — иначе после Keycloak SSO logout
  // browser сохранил бы стейл refresh token (security trail).
  response.cookies.delete(COOKIE_REFRESH);
  return response;
}

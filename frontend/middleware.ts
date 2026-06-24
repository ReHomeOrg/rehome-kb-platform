/**
 * Middleware-гейт /chat/* — чат только для залогиненных пользователей.
 *
 * Анонимов (нет cookie `kb_session`) редиректим на /login чистым 307 ДО
 * рендера страницы — без meta-refresh «вспышки» оболочки, в отличие от
 * server-component redirect в layout (тот остаётся как defense-in-depth).
 * Реальный энфорсмент — на backend (CHAT_REQUIRE_AUTH → 401).
 *
 * basePath учитывается автоматически: `request.nextUrl` (NextURL) знает про
 * basePath, поэтому `pathname = "/login"` сериализуется как `/login` на
 * help.rehome.one (basePath "") и как `/help/login` на rehome.one/help
 * (basePath "/help"). `nextUrl.pathname` — всегда без basePath.
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { COOKIE_SESSION } from "@/lib/auth/cookies";

export function middleware(request: NextRequest): NextResponse {
  if (request.cookies.has(COOKIE_SESSION)) {
    return NextResponse.next();
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  loginUrl.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/chat", "/chat/:path*"],
};

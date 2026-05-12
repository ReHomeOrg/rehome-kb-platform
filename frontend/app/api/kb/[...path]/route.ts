/**
 * Generic backend API proxy (UI.1 #75) — catch-all `/api/kb/<path>`.
 *
 * Reads HttpOnly `kb_session` cookie server-side, attaches as
 * `Authorization: Bearer`, pipes upstream response back to client.
 *
 * **Не для SSE.** Streaming chat — отдельный proxy `/api/kb-sse/<path>`.
 *
 * Security:
 * - НЕ форвардит upstream `Set-Cookie` (нет нужды — frontend сам управляет
 *   session cookie через Keycloak callback).
 * - НЕ логирует Authorization header.
 * - Cookie проброс только server→backend; client уже шлёт cookie на
 *   frontend через browser.
 */

import { cookies } from "next/headers";
import { NextRequest } from "next/server";

import { COOKIE_SESSION } from "@/lib/auth/cookies";
import { getBackendBaseUrl } from "@/lib/env";

// Headers, которые мы НЕ forward'им upstream (host, content-length set'аются
// сами fetch'ем) ИЛИ обратно (set-cookie не нужен).
const HOP_BY_HOP_HEADERS_TO_DROP = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "set-cookie",
]);

async function proxyTo(
  req: NextRequest,
  pathSegments: string[],
): Promise<Response> {
  const cookieStore = await cookies();
  const session = cookieStore.get(COOKIE_SESSION)?.value;
  // Используем `req.url` (parsed через URL) вместо `req.nextUrl.search`,
  // чтобы код был тестируем под обычным `Request` (jsdom не имеет
  // полной NextRequest семантики).
  const requestUrl = new URL(req.url);
  const upstreamUrl = `${getBackendBaseUrl()}/${pathSegments.join("/")}${requestUrl.search}`;

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const accept = req.headers.get("accept");
  if (accept) headers.set("Accept", accept);
  const chatToken = req.headers.get("x-chat-session-token");
  if (chatToken) headers.set("X-Chat-Session-Token", chatToken);
  if (session) headers.set("Authorization", `Bearer ${session}`);

  // Body: GET/HEAD/DELETE — без body; иначе arrayBuffer (поддержка binary).
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const body = hasBody ? await req.arrayBuffer() : undefined;

  const upstreamResp = await fetch(upstreamUrl, {
    method: req.method,
    headers,
    body,
    // Не следуем за redirects — frontend сам решает.
    redirect: "manual",
  });

  // Forward response: status + body + selected headers.
  const responseHeaders = new Headers();
  upstreamResp.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS_TO_DROP.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new Response(upstreamResp.body, {
    status: upstreamResp.status,
    headers: responseHeaders,
  });
}

interface RouteContext {
  params: Promise<{ path: string[] }>;
}

export async function GET(req: NextRequest, ctx: RouteContext): Promise<Response> {
  return proxyTo(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: RouteContext): Promise<Response> {
  return proxyTo(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: RouteContext): Promise<Response> {
  return proxyTo(req, (await ctx.params).path);
}
export async function PATCH(req: NextRequest, ctx: RouteContext): Promise<Response> {
  return proxyTo(req, (await ctx.params).path);
}
export async function DELETE(
  req: NextRequest,
  ctx: RouteContext,
): Promise<Response> {
  return proxyTo(req, (await ctx.params).path);
}

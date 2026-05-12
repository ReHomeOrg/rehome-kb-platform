/**
 * SSE proxy (UI.1 #75) — `/api/kb-sse/<path>`.
 *
 * Используется для chat streaming (`POST /api/v1/chat/sessions/{id}/messages`
 * с `Accept: text/event-stream`). Pipes upstream stream без буферизации.
 *
 * Production-нюансы (Reviewer note #7):
 * - `X-Accel-Buffering: no` — отключает proxy-буфер у nginx.
 * - `Connection: keep-alive` — long-lived stream.
 * - `Cache-Control: no-cache` — браузерные/proxy кэши не буферят.
 */

import { cookies } from "next/headers";
import { NextRequest } from "next/server";

import { COOKIE_SESSION } from "@/lib/auth/cookies";
import { getBackendBaseUrl } from "@/lib/env";

interface RouteContext {
  params: Promise<{ path: string[] }>;
}

export async function POST(req: NextRequest, ctx: RouteContext): Promise<Response> {
  const { path } = await ctx.params;
  const cookieStore = await cookies();
  const session = cookieStore.get(COOKIE_SESSION)?.value;

  const headers = new Headers({
    "Content-Type": req.headers.get("content-type") ?? "application/json",
    Accept: "text/event-stream",
  });
  const chatToken = req.headers.get("x-chat-session-token");
  if (chatToken) headers.set("X-Chat-Session-Token", chatToken);
  if (session) headers.set("Authorization", `Bearer ${session}`);

  const requestUrl = new URL(req.url);
  const upstreamUrl = `${getBackendBaseUrl()}/${path.join("/")}${requestUrl.search}`;
  const body = await req.arrayBuffer();
  const upstreamResp = await fetch(upstreamUrl, {
    method: "POST",
    headers,
    body,
  });

  // Если upstream упал ДО stream-start (e.g. 404, 401) — pipe как обычный
  // response, без SSE headers (caller получит ApiError через parseSseStream).
  if (!upstreamResp.ok) {
    const errBody = await upstreamResp.text();
    return new Response(errBody, {
      status: upstreamResp.status,
      headers: {
        "Content-Type":
          upstreamResp.headers.get("content-type") ?? "application/json",
      },
    });
  }

  return new Response(upstreamResp.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      // Reviewer note #7: nginx prod не буферит chunks
      "X-Accel-Buffering": "no",
    },
  });
}

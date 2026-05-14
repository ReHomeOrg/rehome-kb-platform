/**
 * GET /api/auth/session-info (#169)
 *
 * Public helper для client-side pre-emptive refresh scheduling.
 * Returns `{ exp: number | null }` — expiration timestamp access_token'а
 * (Unix seconds), либо `null` если сессии нет / cookie malformed.
 *
 * НЕ leak'ает sensitive data: только expiration timestamp,
 * остальные claims (`sub`, `roles`) уже доступны через /whoami endpoint
 * для authenticated callers.
 *
 * Cache: `Cache-Control: no-store` — клиент должен делать fresh fetch
 * после каждого refresh (новый exp).
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { COOKIE_SESSION } from "@/lib/auth/cookies";
import { decodeJwtClaims } from "@/lib/auth/jwt";

export async function GET(): Promise<NextResponse> {
  const cookieStore = await cookies();
  const session = cookieStore.get(COOKIE_SESSION)?.value;
  if (!session) {
    return NextResponse.json(
      { exp: null },
      { status: 200, headers: { "Cache-Control": "no-store" } },
    );
  }
  const claims = decodeJwtClaims(session);
  const exp = claims?.exp ?? null;
  return NextResponse.json(
    { exp },
    { status: 200, headers: { "Cache-Control": "no-store" } },
  );
}

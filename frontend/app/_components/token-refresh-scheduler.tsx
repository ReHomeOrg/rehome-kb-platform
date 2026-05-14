"use client";

/**
 * Pre-emptive token refresh scheduler (#169).
 *
 * Mounted в root layout — runs on every authenticated page. Schedules
 * refresh за `LEAD_TIME_SECONDS` до expiry, чтобы юзер не видел
 * 401 → /refresh roundtrip latency на следующем API call'е.
 *
 * Fallback: existing `apiFetch` retries on 401 (см. #159). Этот компонент
 * — оптимизация, не replacement.
 *
 * Lifecycle:
 * 1. Mount → GET /api/auth/session-info → если exp есть, schedule timer.
 * 2. Timer fires → POST /api/auth/refresh → GET /api/auth/session-info →
 *    reschedule.
 * 3. Refresh fail → silent fallback (next API call → 401 → user redirect).
 * 4. Unmount → clearTimeout.
 *
 * Скрытый component — render'ит null. Side effects only.
 */

import { useEffect } from "react";

const LEAD_TIME_SECONDS = 60;
const MIN_TIMEOUT_MS = 1_000;
const MAX_TIMEOUT_MS = 30 * 60 * 1_000; // 30 minutes safety cap

async function _fetchExp(): Promise<number | null> {
  try {
    const r = await fetch("/api/auth/session-info", {
      cache: "no-store",
    });
    if (!r.ok) return null;
    const body = (await r.json()) as { exp: number | null };
    return body.exp;
  } catch {
    return null;
  }
}

async function _doRefresh(): Promise<boolean> {
  try {
    const r = await fetch("/api/auth/refresh", {
      method: "POST",
      cache: "no-store",
    });
    return r.ok;
  } catch {
    return false;
  }
}

function _computeTimeoutMs(expSeconds: number): number {
  const nowSeconds = Date.now() / 1_000;
  const secondsUntilExpiry = expSeconds - nowSeconds;
  const secondsUntilRefresh = secondsUntilExpiry - LEAD_TIME_SECONDS;
  const ms = secondsUntilRefresh * 1_000;
  // Bounded: minimal 1s (если token уже почти expired — fire immediately),
  // maximum 30 min (long-lived tokens → периодический heartbeat).
  return Math.max(MIN_TIMEOUT_MS, Math.min(MAX_TIMEOUT_MS, ms));
}

export default function TokenRefreshScheduler(): null {
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    async function scheduleNext(): Promise<void> {
      if (cancelled) return;
      const exp = await _fetchExp();
      if (cancelled) return;
      if (exp === null) {
        // Сессии нет — не schedulим. Login flow handles.
        return;
      }
      const timeoutMs = _computeTimeoutMs(exp);
      timer = setTimeout(async () => {
        const ok = await _doRefresh();
        if (cancelled) return;
        // Refresh outcome: ok → reschedule (новый exp); fail → silent,
        // apiFetch.retry или user navigation отработают edge case.
        if (ok) {
          await scheduleNext();
        }
      }, timeoutMs);
    }

    void scheduleNext();

    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, []);

  return null;
}

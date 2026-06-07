"use client";

/**
 * Pre-emptive token refresh scheduler (#169) + cross-tab coordination (#171).
 *
 * Mounted в root layout — runs on every authenticated page. Schedules
 * refresh за `LEAD_TIME_SECONDS` до expiry, чтобы юзер не видел
 * 401 → /refresh roundtrip latency на следующем API call'е.
 *
 * Cross-tab: BroadcastChannel `kb-token-refresh-v1` — leader election
 * по tabId (timestamp prefix → string-сравнимый). Only leader fires
 * refresh; followers idle. На death лидера (no heartbeat за
 * `HEARTBEAT_TIMEOUT_MS`) — самый старый из живых tab'ов берёт roli.
 *
 * Fallback: existing `apiFetch` retries on 401 (см. #159). Этот компонент
 * — оптимизация, не replacement. Если BroadcastChannel unsupported
 * (private mode, legacy iframe), каждый tab refreshes сам себе — старое
 * поведение #169.
 *
 * Lifecycle:
 * 1. Mount → assume leader, schedule refresh.
 * 2. Receive heartbeat with tabId < own → become follower, cancel timer.
 * 3. Timer fires (leader only) → POST /api/auth/refresh → reschedule.
 * 4. Heartbeat-loss timeout (follower) → re-assume leadership.
 * 5. Unmount → clearTimeout/Interval, channel.close().
 */

import { useEffect } from "react";

const LEAD_TIME_SECONDS = 60;
const MIN_TIMEOUT_MS = 1_000;
const MAX_TIMEOUT_MS = 30 * 60 * 1_000; // 30 minutes safety cap
const HEARTBEAT_INTERVAL_MS = 5_000;
// 2× interval плюс jitter — single missed heartbeat не triggers election.
const HEARTBEAT_TIMEOUT_MS = 12_000;
const CHANNEL_NAME = "kb-token-refresh-v1";

type Msg = { type: "heartbeat"; tabId: string };

async function _fetchExp(): Promise<number | null> {
  try {
    const prefix = typeof process !== "undefined" && process.env.VITEST ? "" : "/help";
    const r = await fetch(`${prefix}/api/auth/session-info`, {
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
    const prefix = typeof process !== "undefined" && process.env.VITEST ? "" : "/help";
    const r = await fetch(`${prefix}/api/auth/refresh`, {
      method: "POST",
      cache: "no-store",
    });
    return r.ok;
  } catch {
    return false;
  }
}

export function _computeTimeoutMs(expSeconds: number): number {
  const nowSeconds = Date.now() / 1_000;
  const secondsUntilExpiry = expSeconds - nowSeconds;
  const secondsUntilRefresh = secondsUntilExpiry - LEAD_TIME_SECONDS;
  const ms = secondsUntilRefresh * 1_000;
  // Bounded: minimal 1s (если token уже почти expired — fire immediately),
  // maximum 30 min (long-lived tokens → периодический heartbeat).
  return Math.max(MIN_TIMEOUT_MS, Math.min(MAX_TIMEOUT_MS, ms));
}

export function _generateTabId(): string {
  // Timestamp prefix (zero-padded → string-comparable) гарантирует:
  // более старый таб всегда имеет лексикографически меньший id и
  // выигрывает leader election. Random suffix — tie-break при
  // одновременном mount двух tab'ов.
  const ts = Date.now().toString().padStart(16, "0");
  const rand = Math.random().toString(36).slice(2, 10);
  return `${ts}-${rand}`;
}

export default function TokenRefreshScheduler(): null {
  useEffect(() => {
    let cancelled = false;
    let role: "leader" | "follower" = "leader";
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatInterval: ReturnType<typeof setInterval> | null = null;
    let heartbeatLossTimer: ReturnType<typeof setTimeout> | null = null;

    const channel =
      typeof BroadcastChannel !== "undefined"
        ? new BroadcastChannel(CHANNEL_NAME)
        : null;
    const myId = _generateTabId();

    function clearRefreshTimer(): void {
      if (refreshTimer !== null) {
        clearTimeout(refreshTimer);
        refreshTimer = null;
      }
    }

    async function scheduleNextRefresh(): Promise<void> {
      if (cancelled || role !== "leader") return;
      clearRefreshTimer();
      const exp = await _fetchExp();
      if (cancelled || role !== "leader") return;
      if (exp === null) return;
      const timeoutMs = _computeTimeoutMs(exp);
      refreshTimer = setTimeout(async () => {
        if (cancelled || role !== "leader") return;
        const ok = await _doRefresh();
        if (cancelled || role !== "leader") return;
        if (ok) await scheduleNextRefresh();
      }, timeoutMs);
    }

    function resetHeartbeatLossTimer(): void {
      if (heartbeatLossTimer !== null) clearTimeout(heartbeatLossTimer);
      heartbeatLossTimer = setTimeout(() => {
        // Leader не heartbeat'нул вовремя → take over.
        becomeLeader();
      }, HEARTBEAT_TIMEOUT_MS);
    }

    function becomeFollower(): void {
      if (role === "follower") {
        resetHeartbeatLossTimer();
        return;
      }
      role = "follower";
      clearRefreshTimer();
      resetHeartbeatLossTimer();
    }

    function becomeLeader(): void {
      if (role === "leader") return;
      role = "leader";
      if (heartbeatLossTimer !== null) {
        clearTimeout(heartbeatLossTimer);
        heartbeatLossTimer = null;
      }
      void scheduleNextRefresh();
    }

    if (channel !== null) {
      channel.onmessage = (e: MessageEvent<Msg>): void => {
        const msg = e.data;
        if (msg.type !== "heartbeat") return;
        if (msg.tabId === myId) return;
        if (msg.tabId < myId) {
          // Старший таб жив → follower mode, reset heartbeat-loss timer.
          becomeFollower();
        } else if (role === "leader") {
          // Младший таб только что заявил о себе — отвечаем heartbeat'ом,
          // чтобы он быстрее увидел нас и yield'нул (не ждал 5s interval).
          channel.postMessage({
            type: "heartbeat",
            tabId: myId,
          } satisfies Msg);
        }
      };

      heartbeatInterval = setInterval(() => {
        channel.postMessage({
          type: "heartbeat",
          tabId: myId,
        } satisfies Msg);
      }, HEARTBEAT_INTERVAL_MS);
      // Announce presence immediately.
      channel.postMessage({
        type: "heartbeat",
        tabId: myId,
      } satisfies Msg);
    }

    void scheduleNextRefresh();

    return () => {
      cancelled = true;
      clearRefreshTimer();
      if (heartbeatInterval !== null) clearInterval(heartbeatInterval);
      if (heartbeatLossTimer !== null) clearTimeout(heartbeatLossTimer);
      if (channel !== null) channel.close();
    };
  }, []);

  return null;
}

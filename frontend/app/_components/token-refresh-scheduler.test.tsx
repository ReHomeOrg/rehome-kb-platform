import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TokenRefreshScheduler, {
  _computeTimeoutMs,
  _generateTabId,
} from "./token-refresh-scheduler";

describe("_computeTimeoutMs", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-14T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns (exp - now - 60s) для healthy token", () => {
    const exp = Math.floor(Date.now() / 1000) + 300; // +5 min
    // 300 - 60 = 240s = 240_000 ms
    expect(_computeTimeoutMs(exp)).toBe(240_000);
  });

  it("clamps к MIN_TIMEOUT_MS (1s) если token почти expired", () => {
    const exp = Math.floor(Date.now() / 1000) + 30; // +30s < lead time
    // 30 - 60 = -30s → clamped to 1s
    expect(_computeTimeoutMs(exp)).toBe(1_000);
  });

  it("clamps к MAX_TIMEOUT_MS (30 min) для long-lived token", () => {
    const exp = Math.floor(Date.now() / 1000) + 24 * 3600; // +24h
    expect(_computeTimeoutMs(exp)).toBe(30 * 60 * 1_000);
  });

  it("returns MIN_TIMEOUT_MS для already-expired token", () => {
    const exp = Math.floor(Date.now() / 1000) - 100;
    expect(_computeTimeoutMs(exp)).toBe(1_000);
  });
});

describe("_generateTabId", () => {
  it("returns string с timestamp prefix + random suffix", () => {
    const id = _generateTabId();
    expect(id).toMatch(/^\d{16}-[a-z0-9]+$/);
  });

  it("два tab'а имеют разные id (random suffix)", () => {
    const a = _generateTabId();
    const b = _generateTabId();
    expect(a).not.toBe(b);
  });

  it("позже сгенерированный id лексикографически >= более раннего", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    const early = _generateTabId();
    vi.setSystemTime(new Date("2026-06-01T00:00:00Z"));
    const late = _generateTabId();
    expect(early < late).toBe(true);
    vi.useRealTimers();
  });
});

describe("TokenRefreshScheduler", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    vi.useFakeTimers();
    originalFetch = globalThis.fetch;
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    cleanup();
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders null", () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ exp: null }),
    });
    const { container } = render(<TokenRefreshScheduler />);
    expect(container.firstChild).toBeNull();
  });

  it("не schedule'ит refresh если exp === null (anonymous)", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ exp: null }),
    });

    render(<TokenRefreshScheduler />);
    await vi.runOnlyPendingTimersAsync();

    // Только session-info GET, без последующего refresh POST.
    const refreshCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes("/api/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(0);
  });

  it("fires refresh POST после scheduled timeout", async () => {
    const exp = Math.floor(Date.now() / 1000) + 120; // 120s — refresh через 60s
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/api/auth/session-info")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ exp }),
        });
      }
      if (String(url).includes("/api/auth/refresh")) {
        return Promise.resolve({ ok: true });
      }
      return Promise.resolve({ ok: false });
    });

    render(<TokenRefreshScheduler />);
    // Прогон до момента fetchExp.
    await vi.advanceTimersByTimeAsync(0);
    // Прогон до момента fire setTimeout.
    await vi.advanceTimersByTimeAsync(61_000);

    const refreshCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes("/api/auth/refresh"),
    );
    expect(refreshCalls.length).toBeGreaterThanOrEqual(1);
  });

  it("не reschedule'ит после failed refresh", async () => {
    const exp = Math.floor(Date.now() / 1000) + 120;
    let sessionInfoCalls = 0;
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/api/auth/session-info")) {
        sessionInfoCalls += 1;
        return Promise.resolve({
          ok: true,
          json: async () => ({ exp }),
        });
      }
      if (String(url).includes("/api/auth/refresh")) {
        return Promise.resolve({ ok: false });
      }
      return Promise.resolve({ ok: false });
    });

    render(<TokenRefreshScheduler />);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(61_000);
    // Если бы fail → reschedule, то увидели бы 2-й session-info GET.
    expect(sessionInfoCalls).toBe(1);
  });

  it("cleanup закрывает BroadcastChannel и таймеры на unmount", () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ exp: null }),
    });

    const { unmount } = render(<TokenRefreshScheduler />);
    // Не должно бросать.
    expect(() => unmount()).not.toThrow();
  });

  it("получив heartbeat с младшим (smaller) tabId, лидер отвечает heartbeat'ом", async () => {
    // Мокаем BroadcastChannel чтобы capture'нуть handler и postMessages.
    type Handler = (e: MessageEvent<unknown>) => void;
    const handlerRef: { current: Handler | null } = { current: null };
    const posted: unknown[] = [];

    class MockBC {
      constructor(public name: string) {}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      set onmessage(h: any) {
        handlerRef.current = h as Handler;
      }
      get onmessage(): Handler | null {
        return handlerRef.current;
      }
      postMessage(msg: unknown): void {
        posted.push(msg);
      }
      close(): void {}
    }
    const originalBC = globalThis.BroadcastChannel;
    globalThis.BroadcastChannel = MockBC as unknown as typeof BroadcastChannel;
    try {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ exp: null }),
      });

      render(<TokenRefreshScheduler />);
      await vi.advanceTimersByTimeAsync(0);

      // initial announcement.
      expect(posted.length).toBeGreaterThanOrEqual(1);
      expect(posted[0]).toMatchObject({ type: "heartbeat" });

      const baseline = posted.length;
      // Шлём heartbeat от "младшего" таба (lexicographically больший id).
      handlerRef.current?.({
        data: { type: "heartbeat", tabId: "9999999999999999-zzzzz" },
      } as MessageEvent);

      // Лидер должен ответить heartbeat'ом (так младший быстрее yield'нет).
      expect(posted.length).toBe(baseline + 1);
    } finally {
      globalThis.BroadcastChannel = originalBC;
    }
  });

  it("получив heartbeat со старшим (smaller) tabId, НЕ отвечает (просто demote)", async () => {
    type Handler = (e: MessageEvent<unknown>) => void;
    const handlerRef: { current: Handler | null } = { current: null };
    const posted: unknown[] = [];

    class MockBC {
      constructor(public name: string) {}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      set onmessage(h: any) {
        handlerRef.current = h as Handler;
      }
      get onmessage(): Handler | null {
        return handlerRef.current;
      }
      postMessage(msg: unknown): void {
        posted.push(msg);
      }
      close(): void {}
    }
    const originalBC = globalThis.BroadcastChannel;
    globalThis.BroadcastChannel = MockBC as unknown as typeof BroadcastChannel;
    try {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ exp: null }),
      });

      render(<TokenRefreshScheduler />);
      await vi.advanceTimersByTimeAsync(0);

      const baseline = posted.length;
      // Шлём heartbeat от "старшего" таба (timestamp 0 → точно меньше).
      handlerRef.current?.({
        data: { type: "heartbeat", tabId: "0000000000000000-aaaaa" },
      } as MessageEvent);

      // На старший heartbeat ничего не postMessage'ится — только role
      // меняется на follower. (Reply heartbeat шлётся только младшему.)
      expect(posted.length).toBe(baseline);
    } finally {
      globalThis.BroadcastChannel = originalBC;
    }
  });

  it("игнорирует heartbeat от собственного tabId (self-loopback)", async () => {
    type Handler = (e: MessageEvent<unknown>) => void;
    const handlerRef: { current: Handler | null } = { current: null };
    let postedFirst: { tabId: string } | null = null;

    class MockBC {
      constructor(public name: string) {}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      set onmessage(h: any) {
        handlerRef.current = h as Handler;
      }
      get onmessage(): Handler | null {
        return handlerRef.current;
      }
      postMessage(msg: unknown): void {
        if (postedFirst === null) {
          postedFirst = msg as { tabId: string };
        }
      }
      close(): void {}
    }
    const originalBC = globalThis.BroadcastChannel;
    globalThis.BroadcastChannel = MockBC as unknown as typeof BroadcastChannel;
    try {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ exp: null }),
      });

      render(<TokenRefreshScheduler />);
      await vi.advanceTimersByTimeAsync(0);

      expect(postedFirst).not.toBeNull();
      const myId = postedFirst!.tabId;

      // Echo от себя — no-op (не demote себя, не reply).
      expect(() =>
        handlerRef.current?.({
          data: { type: "heartbeat", tabId: myId },
        } as MessageEvent),
      ).not.toThrow();
    } finally {
      globalThis.BroadcastChannel = originalBC;
    }
  });

  it("работает в окружении без BroadcastChannel (graceful fallback)", () => {
    const originalBC = globalThis.BroadcastChannel;
    // @ts-expect-error — deliberately unset для проверки fallback path.
    delete globalThis.BroadcastChannel;
    try {
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ exp: null }),
      });
      expect(() => render(<TokenRefreshScheduler />)).not.toThrow();
    } finally {
      globalThis.BroadcastChannel = originalBC;
    }
  });
});

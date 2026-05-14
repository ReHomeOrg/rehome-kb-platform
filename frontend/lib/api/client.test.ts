import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "./client";

// Mock next/headers globally — некоторые тесты симулируют SSR.
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: (name: string): { value: string } | undefined =>
      name === "kb_session" ? { value: "test-jwt-token" } : undefined,
  })),
}));

describe("ApiError", () => {
  it("is instance of Error", () => {
    const err = new ApiError(404, { detail: "not found" });
    expect(err).toBeInstanceOf(Error);
    expect(err.status).toBe(404);
    expect(err.body).toEqual({ detail: "not found" });
  });

  it("has default message including status", () => {
    const err = new ApiError(500, null);
    expect(err.message).toContain("500");
  });
});

describe("apiFetch (browser mode)", () => {
  const originalWindow = (globalThis as { window?: unknown }).window;
  const fetchMock = vi.fn();

  beforeEach(() => {
    (globalThis as { window?: unknown }).window = {}; // simulate browser
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    fetchMock.mockReset();
  });

  afterEach(() => {
    (globalThis as { window?: unknown }).window = originalWindow;
  });

  it("uses relative /api/kb proxy URL in browser", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await apiFetch("/api/v1/articles");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/kb/api/v1/articles");
  });

  it("does NOT add Authorization in browser (proxy attaches)", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await apiFetch("/api/v1/articles");
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("Authorization")).toBeNull();
  });

  it("throws ApiError on 4xx with parsed JSON body", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
    );
    await expect(apiFetch("/api/v1/articles/x")).rejects.toMatchObject({
      status: 404,
      body: { detail: "not found" },
    });
  });

  it("throws ApiError on 5xx with text body on parse failure", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("internal error", { status: 500 }),
    );
    await expect(apiFetch("/api/v1/articles")).rejects.toMatchObject({
      status: 500,
    });
  });

  it("returns undefined on 204 No Content", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(apiFetch("/api/v1/x")).resolves.toBeUndefined();
  });

  it("sets Content-Type application/json by default", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await apiFetch("/api/v1/articles");
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("network error propagates", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(apiFetch("/api/v1/x")).rejects.toThrow("fetch failed");
  });

  // --- Refresh token flow (#161) -------------------------------------

  it("401 triggers /api/auth/refresh + retry original request", async () => {
    fetchMock
      // 1) Original — 401
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
      )
      // 2) Refresh call — success
      .mockResolvedValueOnce(new Response("{}", { status: 200 }))
      // 3) Retry original — success
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
      );

    const result = await apiFetch<{ ok: boolean }>("/api/v1/articles");
    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    // 2-я call — refresh endpoint, POST.
    const [refreshUrl, refreshInit] = fetchMock.mock.calls[1];
    expect(refreshUrl).toBe("/api/auth/refresh");
    expect((refreshInit as RequestInit).method).toBe("POST");
  });

  it("401 → refresh fail → throw ApiError(401)", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
      )
      .mockResolvedValueOnce(new Response("", { status: 401 })); // refresh fail

    await expect(apiFetch("/api/v1/articles")).rejects.toMatchObject({
      status: 401,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("401 → refresh success → retry — НО retry тоже 401 → no infinite loop", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockResolvedValueOnce(new Response("{}", { status: 200 })) // refresh OK
      .mockResolvedValueOnce(new Response("", { status: 401 })); // retry — 401

    await expect(apiFetch("/api/v1/x")).rejects.toMatchObject({ status: 401 });
    // Только один refresh attempt, не infinite loop.
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("refresh fetch throws network error → fall through к ApiError(401)", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockRejectedValueOnce(new TypeError("refresh net error"));

    await expect(apiFetch("/api/v1/x")).rejects.toMatchObject({ status: 401 });
  });
});

// SSR-mode тесты вынесены в `client.ssr.test.ts` с
// `// @vitest-environment node` директивой — jsdom не позволяет
// удалить `globalThis.window` (зависание window-object'а).

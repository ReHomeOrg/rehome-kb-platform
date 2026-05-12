// @vitest-environment node
/**
 * SSR-mode тесты для apiFetch.
 *
 * Vitest node environment гарантирует, что `globalThis.window`
 * undefined — это то, что видит реальный Server Component при SSR.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: (name: string): { value: string } | undefined =>
      name === "kb_session" ? { value: "test-jwt-token" } : undefined,
  })),
}));

const ORIGINAL_URL = process.env.BACKEND_BASE_URL;
const fetchMock = vi.fn();

beforeEach(() => {
  process.env.BACKEND_BASE_URL = "http://backend-test:8000";
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  if (ORIGINAL_URL === undefined) {
    delete process.env.BACKEND_BASE_URL;
  } else {
    process.env.BACKEND_BASE_URL = ORIGINAL_URL;
  }
});

describe("apiFetch (SSR / node env)", () => {
  it("uses absolute backend URL", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await apiFetch("/api/v1/articles");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://backend-test:8000/api/v1/articles");
  });

  it("attaches Authorization Bearer from kb_session cookie", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await apiFetch("/api/v1/articles");
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("Authorization")).toBe("Bearer test-jwt-token");
  });
});

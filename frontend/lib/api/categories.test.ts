import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listCategories } from "./categories";

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: () => undefined })),
}));

const originalWindow = (globalThis as { window?: unknown }).window;
const fetchMock = vi.fn();

beforeEach(() => {
  (globalThis as { window?: unknown }).window = {};
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

describe("categories API", () => {
  it("listCategories GETs /api/v1/categories", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [] })),
    );
    await listCategories();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/v1/categories");
    expect((init as RequestInit).method ?? "GET").toBe("GET");
  });
});

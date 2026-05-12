import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listTags } from "./tags";

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

describe("tags API", () => {
  it("encodes q and limit", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ data: [] })));
    await listTags({ q: "договор", limit: 20 });
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("q=");
    expect(String(url)).toContain("limit=20");
  });

  it("empty filters → no query string", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ data: [] })));
    await listTags();
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain("?");
  });
});

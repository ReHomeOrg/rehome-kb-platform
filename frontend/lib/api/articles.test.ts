import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getArticle,
  getArticleHistory,
  listArticles,
  searchArticles,
} from "./articles";

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: () => undefined })),
}));

const originalWindow = (globalThis as { window?: unknown }).window;
const fetchMock = vi.fn();

beforeEach(() => {
  (globalThis as { window?: unknown }).window = {}; // browser mode
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

describe("articles API", () => {
  it("listArticles encodes filters into query string", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ data: [], pagination: { cursor_next: null, has_more: false } }),
      ),
    );
    await listArticles({ category: "rental", limit: 5 });
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("category=rental");
    expect(String(url)).toContain("limit=5");
  });

  it("listArticles without filters omits query string", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ data: [], pagination: { cursor_next: null, has_more: false } }),
      ),
    );
    await listArticles();
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain("?");
  });

  it("getArticle URL-encodes slug", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ slug: "x", id: "x" })),
    );
    await getArticle("сервисный-платёж");
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(encodeURIComponent("сервисный-платёж"));
  });

  it("getArticleHistory URL-encodes slug + hits /history endpoint", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [] })),
    );
    await getArticleHistory("сервисный-платёж");
    const [url] = fetchMock.mock.calls[0];
    const s = String(url);
    expect(s).toContain(encodeURIComponent("сервисный-платёж"));
    expect(s).toContain("/history");
  });

  it("searchArticles POSTs JSON body", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ data: [], pagination: { cursor_next: null, has_more: false } }),
      ),
    );
    await searchArticles({ q: "договор", limit: 10 });
    const [, init] = fetchMock.mock.calls[0];
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      q: "договор",
      limit: 10,
    });
  });
});

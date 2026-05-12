import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getDocument, listDocuments } from "./documents";

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

describe("documents API", () => {
  it("listDocuments with category + status", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          data: [],
          pagination: { cursor_next: null, has_more: false },
        }),
      ),
    );
    await listDocuments({ category: "B", status: "ACTIVE" });
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("category=B");
    expect(String(url)).toContain("status=ACTIVE");
  });

  it("getDocument encodes UUID path", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ id: "x" })));
    const uuid = "a1b2c3d4-1234-5678-9abc-def012345678";
    await getDocument(uuid);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/documents/${uuid}`);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createWebhook,
  deleteWebhook,
  listWebhooks,
  testWebhook,
} from "./webhooks";

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

describe("webhooks API", () => {
  it("listWebhooks GETs /api/v1/webhooks", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ data: [] })));
    await listWebhooks();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/v1/webhooks");
    expect((init as RequestInit | undefined)?.method ?? "GET").toBe("GET");
  });

  it("createWebhook POSTs JSON body", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "u", secret: "s" })),
    );
    await createWebhook({
      url: "https://example.com/h",
      events: ["article.published"],
      description: "test",
    });
    const [, init] = fetchMock.mock.calls[0];
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.url).toBe("https://example.com/h");
    expect(body.events).toEqual(["article.published"]);
  });

  it("deleteWebhook DELETEs by id, encoding it", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await deleteWebhook("abc/123");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/v1/webhooks/abc%2F123");
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("testWebhook POSTs to /{id}/test and returns delivery_id", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ delivery_id: "d-uuid", status: "enqueued" }),
      ),
    );
    const result = await testWebhook("wh-uuid");
    expect(result.delivery_id).toBe("d-uuid");
    expect(result.status).toBe("enqueued");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/v1/webhooks/wh-uuid/test");
    expect((init as RequestInit).method).toBe("POST");
  });
});

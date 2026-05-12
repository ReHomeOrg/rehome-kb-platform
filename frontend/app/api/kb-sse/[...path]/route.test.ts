import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

const cookieStoreMock = {
  get: vi.fn<(name: string) => { value: string } | undefined>(),
};

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => cookieStoreMock),
}));

const ORIGINAL = process.env.BACKEND_BASE_URL;
const fetchMock = vi.fn();

beforeEach(() => {
  process.env.BACKEND_BASE_URL = "http://backend:8000";
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  cookieStoreMock.get.mockReset();
});

afterEach(() => {
  if (ORIGINAL === undefined) {
    delete process.env.BACKEND_BASE_URL;
  } else {
    process.env.BACKEND_BASE_URL = ORIGINAL;
  }
});

function ctx(parts: string[]): { params: Promise<{ path: string[] }> } {
  return { params: Promise.resolve({ path: parts }) };
}

describe("kb-sse proxy route", () => {
  it("returns 200 with text/event-stream content-type on success", async () => {
    cookieStoreMock.get.mockReturnValueOnce({ value: "jwt" });
    fetchMock.mockResolvedValueOnce(
      new Response("event: chunk\ndata: {\"text\":\"hi\"}\n\n", {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    const req = new Request(
      "http://localhost:3000/api/kb-sse/api/v1/chat/sessions/s/messages",
      {
        method: "POST",
        body: JSON.stringify({ content: "hi" }),
        headers: {
          "Content-Type": "application/json",
          "X-Chat-Session-Token": "tok",
        },
      },
    );
    const response = await POST(
      req as unknown as Parameters<typeof POST>[0],
      ctx(["api", "v1", "chat", "sessions", "s", "messages"]),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/event-stream");
    expect(response.headers.get("Cache-Control")).toBe("no-cache");
    expect(response.headers.get("X-Accel-Buffering")).toBe("no");
  });

  it("attaches Bearer + X-Chat-Session-Token upstream", async () => {
    cookieStoreMock.get.mockReturnValueOnce({ value: "jwt-token" });
    fetchMock.mockResolvedValueOnce(
      new Response("", {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    const req = new Request(
      "http://localhost:3000/api/kb-sse/api/v1/chat/sessions/s/messages",
      {
        method: "POST",
        body: JSON.stringify({ content: "hi" }),
        headers: {
          "Content-Type": "application/json",
          "X-Chat-Session-Token": "tok",
        },
      },
    );
    await POST(
      req as unknown as Parameters<typeof POST>[0],
      ctx(["api", "v1", "chat", "sessions", "s", "messages"]),
    );
    const [, init] = fetchMock.mock.calls[0];
    const headers = (init as RequestInit).headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer jwt-token");
    expect(headers.get("X-Chat-Session-Token")).toBe("tok");
    expect(headers.get("Accept")).toBe("text/event-stream");
  });

  it("returns upstream error before stream start as plain response", async () => {
    cookieStoreMock.get.mockReturnValueOnce(undefined);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const req = new Request(
      "http://localhost:3000/api/kb-sse/api/v1/chat/sessions/missing/messages",
      {
        method: "POST",
        body: JSON.stringify({ content: "x" }),
        headers: { "Content-Type": "application/json" },
      },
    );
    const response = await POST(
      req as unknown as Parameters<typeof POST>[0],
      ctx(["api", "v1", "chat", "sessions", "missing", "messages"]),
    );
    expect(response.status).toBe(404);
    expect(response.headers.get("Content-Type")).toBe("application/json");
    expect(response.headers.get("X-Accel-Buffering")).toBeNull();
  });
});

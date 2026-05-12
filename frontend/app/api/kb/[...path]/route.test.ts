import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "./route";

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

function makeRequest(method: string, path: string, body?: string): Request {
  return new Request(`http://localhost:3000/api/kb/${path}`, {
    method,
    body,
    headers: body ? { "Content-Type": "application/json" } : undefined,
  });
}

function makeCtx(pathSegments: string[]): { params: Promise<{ path: string[] }> } {
  return { params: Promise.resolve({ path: pathSegments }) };
}

describe("kb proxy route", () => {
  it("GET forwards to backend with Bearer if cookie present", async () => {
    cookieStoreMock.get.mockReturnValueOnce({ value: "jwt-token" });
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const req = makeRequest("GET", "api/v1/articles");
    // NextRequest extends Request — для теста используем Request
    const response = await GET(
      req as unknown as Parameters<typeof GET>[0],
      makeCtx(["api", "v1", "articles"]),
    );
    expect(response.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://backend:8000/api/v1/articles");
    const headers = (init as RequestInit).headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer jwt-token");
  });

  it("GET without cookie omits Authorization (public endpoint)", async () => {
    cookieStoreMock.get.mockReturnValueOnce(undefined);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [] }), { status: 200 }),
    );
    const req = makeRequest("GET", "api/v1/articles");
    await GET(
      req as unknown as Parameters<typeof GET>[0],
      makeCtx(["api", "v1", "articles"]),
    );
    const [, init] = fetchMock.mock.calls[0];
    const headers = (init as RequestInit).headers as Headers;
    expect(headers.get("Authorization")).toBeNull();
  });

  it("POST forwards body to backend", async () => {
    cookieStoreMock.get.mockReturnValueOnce(undefined);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    );
    const req = makeRequest("POST", "api/v1/articles", JSON.stringify({ slug: "x" }));
    const response = await POST(
      req as unknown as Parameters<typeof POST>[0],
      makeCtx(["api", "v1", "articles"]),
    );
    expect(response.status).toBe(201);
    // Body forwarded
    const [, init] = fetchMock.mock.calls[0];
    expect((init as RequestInit).body).toBeDefined();
  });

  it("forwards X-Chat-Session-Token header upstream", async () => {
    cookieStoreMock.get.mockReturnValueOnce(undefined);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "s" }), { status: 200 }),
    );
    const req = new Request("http://localhost:3000/api/kb/api/v1/chat/sessions/s", {
      method: "GET",
      headers: { "X-Chat-Session-Token": "tok-abc" },
    });
    await GET(
      req as unknown as Parameters<typeof GET>[0],
      makeCtx(["api", "v1", "chat", "sessions", "s"]),
    );
    const [, init] = fetchMock.mock.calls[0];
    const headers = (init as RequestInit).headers as Headers;
    expect(headers.get("X-Chat-Session-Token")).toBe("tok-abc");
  });

  it("passes through upstream status and body", async () => {
    cookieStoreMock.get.mockReturnValueOnce(undefined);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
    );
    const req = makeRequest("GET", "api/v1/articles/x");
    const response = await GET(
      req as unknown as Parameters<typeof GET>[0],
      makeCtx(["api", "v1", "articles", "x"]),
    );
    expect(response.status).toBe(404);
    const body = await response.json();
    expect(body).toEqual({ detail: "not found" });
  });

  it("drops upstream Set-Cookie", async () => {
    cookieStoreMock.get.mockReturnValueOnce(undefined);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Set-Cookie": "evil=1" },
      }),
    );
    const req = makeRequest("GET", "api/v1/x");
    const response = await GET(
      req as unknown as Parameters<typeof GET>[0],
      makeCtx(["api", "v1", "x"]),
    );
    expect(response.headers.get("Set-Cookie")).toBeNull();
  });

  it("preserves query string", async () => {
    cookieStoreMock.get.mockReturnValueOnce(undefined);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [] }), { status: 200 }),
    );
    const req = new Request(
      "http://localhost:3000/api/kb/api/v1/articles?category=rental&limit=5",
      { method: "GET" },
    );
    await GET(
      req as unknown as Parameters<typeof GET>[0],
      makeCtx(["api", "v1", "articles"]),
    );
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("?category=rental&limit=5");
  });
});

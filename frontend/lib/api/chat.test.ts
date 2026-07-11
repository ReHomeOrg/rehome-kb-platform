import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSession,
  deleteSession,
  escalate,
  getSession,
  postFeedback,
  sendMessageJson,
} from "./chat";

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

describe("chat API", () => {
  it("createSession returns session + X-Chat-Session-Token header", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "sess-1", scope: "guest" }), {
        status: 201,
        headers: { "X-Chat-Session-Token": "tok-abc" },
      }),
    );
    const result = await createSession();
    expect(result.session.id).toBe("sess-1");
    expect(result.sessionToken).toBe("tok-abc");
  });

  it("createSession without anon header returns null sessionToken", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "sess-1", scope: "tenant" }), {
        status: 201,
      }),
    );
    const result = await createSession();
    expect(result.sessionToken).toBeNull();
  });

  it("getSession adds X-Chat-Session-Token when provided", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "sess-1", messages: [] })),
    );
    await getSession("sess-1", { sessionToken: "tok-abc" });
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("X-Chat-Session-Token")).toBe("tok-abc");
  });

  it("sendMessageJson POSTs content body with Accept JSON", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "m-1", role: "assistant" })),
    );
    await sendMessageJson("s", { content: "hi" }, { sessionToken: "t" });
    const [, init] = fetchMock.mock.calls[0];
    expect((init as RequestInit).method).toBe("POST");
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("Accept")).toBe("application/json");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      content: "hi",
    });
  });

  it("postFeedback sends rating + comment", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 201 }));
    await postFeedback("s", {
      message_id: "m",
      rating: "up",
      comment: "good",
    });
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      message_id: "m",
      rating: "up",
      comment: "good",
    });
  });

  it("escalate returns ticket_id + estimated_time", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ticket_id: "t-1",
          estimated_response_time_minutes: 10,
        }),
        { status: 201 },
      ),
    );
    const result = await escalate("s", { priority: "high" });
    expect(result.estimated_response_time_minutes).toBe(10);
  });

  it("deleteSession sends DELETE", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await deleteSession("s", { sessionToken: "t" });
    const [, init] = fetchMock.mock.calls[0];
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("createSession defaults to empty context body", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "s" }), { status: 201 }),
    );
    await createSession();
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({});
  });

  it("createSession propagates context object", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "s" }), { status: 201 }),
    );
    await createSession({ context: { page_url: "https://x" } });
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.context.page_url).toBe("https://x");
  });

  it("createSession throws ApiError on 4xx", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "bad" }), { status: 422 }),
    );
    await expect(createSession()).rejects.toMatchObject({ status: 422 });
  });

  it("escalate with empty input still POSTs", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ticket_id: "t",
          estimated_response_time_minutes: 30,
        }),
        { status: 201 },
      ),
    );
    await escalate("s");
    const [, init] = fetchMock.mock.calls[0];
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({});
  });

  it("postFeedback without comment", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 201 }));
    await postFeedback("s", { message_id: "m", rating: "down" });
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ message_id: "m", rating: "down" });
  });

  it("getSession without sessionToken — no header", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "s", messages: [] })),
    );
    await getSession("s");
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("X-Chat-Session-Token")).toBeNull();
  });
});

describe("streamMessage SSE parsing", () => {
  it("yields chunks parsed from SSE stream", async () => {
    const { streamMessage } = await import("./chat");
    const body = (
      'event: chunk\ndata: {"text":"Hello"}\n\n' +
      'event: chunk\ndata: {"text":" world"}\n\n' +
      'event: message-end\ndata: {"message_id":"m1","total_tokens":5}\n\n' +
      'event: done\ndata: {}\n\n'
    );
    fetchMock.mockResolvedValueOnce(
      new Response(new TextEncoder().encode(body).buffer, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const ev of streamMessage("s", { content: "hi" })) {
      events.push(ev);
    }
    const names = events.map((e) => e.event);
    expect(names).toEqual(["chunk", "chunk", "message-end", "done"]);
    expect((events[0].data as { text: string }).text).toBe("Hello");
    expect((events[2].data as { message_id: string }).message_id).toBe("m1");
  });

  it("throws ApiError if upstream not ok", async () => {
    const { streamMessage } = await import("./chat");
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
    );
    await expect(async () => {
      for await (const ev of streamMessage("s", { content: "hi" })) {
        void ev;
      }
    }).rejects.toMatchObject({ status: 404 });
    // non-401 → без refresh-retry (единственный fetch).
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("on 401 refreshes token and retries once → streams (#386)", async () => {
    const { streamMessage } = await import("./chat");
    const sse = 'event: chunk\ndata: {"text":"Hi"}\n\n' + "event: done\ndata: {}\n\n";
    fetchMock
      // 1) SSE запрос → 401 (протухший cookie)
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
      )
      // 2) /api/auth/refresh → ok
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      // 3) retry SSE → стрим
      .mockResolvedValueOnce(
        new Response(new TextEncoder().encode(sse).buffer, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const ev of streamMessage("s", { content: "hi" })) {
      events.push(ev);
    }
    expect(events.map((e) => e.event)).toEqual(["chunk", "done"]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/auth/refresh");
  });

  it("on 401 with failed refresh → throws ApiError(401), no retry (#386)", async () => {
    const { streamMessage } = await import("./chat");
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "expired" }), { status: 401 }),
      )
      // refresh не удался (refresh cookie тоже истёк) → r.ok=false
      .mockResolvedValueOnce(new Response(null, { status: 401 }));
    await expect(async () => {
      for await (const ev of streamMessage("s", { content: "hi" })) {
        void ev;
      }
    }).rejects.toMatchObject({ status: 401 });
    // 1 SSE + 1 refresh, без повторного SSE-retry.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

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
});

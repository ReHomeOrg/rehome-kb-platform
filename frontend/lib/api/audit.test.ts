import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { listAudit } from "./audit";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

const apiFetchMock = vi.mocked(apiFetch);

describe("audit API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("no filters → clean URL", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { limit: 50, offset: 0, count: 0 },
    });
    await listAudit();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/audit-log");
  });

  it("encodes filters в querystring", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { limit: 50, offset: 0, count: 0 },
    });
    await listAudit({
      actor_sub: "user-123",
      resource_type: "article",
      action: "articles.created",
      since: "2026-01-01T00:00:00Z",
      limit: 20,
      offset: 40,
    });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("actor_sub=user-123");
    expect(url).toContain("resource_type=article");
    expect(url).toContain("action=articles.created");
    expect(url).toContain("since=2026-01-01T00%3A00%3A00Z");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
  });

  it("omits empty filter values", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { limit: 50, offset: 0, count: 0 },
    });
    await listAudit({ actor_sub: "", resource_type: undefined });
    expect(apiFetchMock.mock.calls[0][0]).toBe("/api/v1/audit-log");
  });

  it("encodes q substring (#183)", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { limit: 50, offset: 0, count: 0 },
    });
    await listAudit({ q: "article-foo" });
    expect(apiFetchMock.mock.calls[0][0]).toContain("q=article-foo");
  });
});

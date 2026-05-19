import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { invalidateCache, triggerReindex } from "./admin-maintenance";

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

describe("triggerReindex", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("sends POST with default scope=all", async () => {
    apiFetchMock.mockResolvedValueOnce({ task_id: "x" });
    await triggerReindex();
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/reindex",
      expect.objectContaining({ method: "POST" }),
    );
    const call = apiFetchMock.mock.calls[0][1] as RequestInit;
    expect(call.body).toBe(JSON.stringify({ scope: "all" }));
  });

  it("sends with explicit scope", async () => {
    apiFetchMock.mockResolvedValueOnce({ task_id: "x" });
    await triggerReindex("articles");
    const call = apiFetchMock.mock.calls[0][1] as RequestInit;
    expect(call.body).toBe(JSON.stringify({ scope: "articles" }));
  });
});

describe("invalidateCache", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("sends DELETE with default scope=all", async () => {
    apiFetchMock.mockResolvedValueOnce({ status: "accepted", scope: "all" });
    await invalidateCache();
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/cache?scope=all",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("encodes scope in URL", async () => {
    apiFetchMock.mockResolvedValueOnce({ status: "accepted", scope: "search" });
    await invalidateCache("search");
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/cache?scope=search",
      expect.any(Object),
    );
  });
});

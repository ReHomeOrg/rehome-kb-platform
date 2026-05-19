import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { startAuditExport } from "./admin-audit-export";

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

describe("startAuditExport", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("sends POST with required from + to", async () => {
    apiFetchMock.mockResolvedValueOnce({ task_id: "x", estimated_ready_at: null });
    await startAuditExport({
      from: "2026-05-01T00:00:00Z",
      to: "2026-05-31T23:59:59Z",
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/audit-log/export",
      expect.objectContaining({ method: "POST" }),
    );
    const call = apiFetchMock.mock.calls[0][1] as RequestInit;
    expect(call.body).toContain('"from":"2026-05-01T00:00:00Z"');
    expect(call.body).toContain('"to":"2026-05-31T23:59:59Z"');
  });

  it("encodes filters + format + reason", async () => {
    apiFetchMock.mockResolvedValueOnce({ task_id: "x", estimated_ready_at: null });
    await startAuditExport({
      from: "2026-05-01T00:00:00Z",
      to: "2026-05-31T23:59:59Z",
      filters: { actor_sub: "u-1", resource_type: "article" },
      format: "json",
      reason: "Запрос РКН №123",
    });
    const call = apiFetchMock.mock.calls[0][1] as RequestInit;
    expect(call.body).toContain('"filters":');
    expect(call.body).toContain('"actor_sub":"u-1"');
    expect(call.body).toContain('"format":"json"');
    expect(call.body).toContain('"reason":"Запрос РКН №123"');
  });
});

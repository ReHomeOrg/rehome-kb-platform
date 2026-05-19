import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { getAdminTask } from "./admin-tasks";

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

describe("getAdminTask", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("calls expected URL with encoded id", async () => {
    apiFetchMock.mockResolvedValueOnce({});
    await getAdminTask("11111111-1111-1111-1111-111111111111");
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/tasks/11111111-1111-1111-1111-111111111111",
    );
  });

  it("returns parsed AdminTaskStatusView shape", async () => {
    const fixture = {
      task_id: "abc",
      type: "reindex",
      status: "COMPLETED",
      progress_percent: 100,
      created_at: "2026-05-01T12:00:00Z",
      completed_at: "2026-05-01T12:05:00Z",
      result_url: null,
      error: null,
    };
    apiFetchMock.mockResolvedValueOnce(fixture);
    const result = await getAdminTask("abc");
    expect(result.task_id).toBe("abc");
    expect(result.type).toBe("reindex");
    expect(result.status).toBe("COMPLETED");
    expect(result.progress_percent).toBe(100);
  });
});

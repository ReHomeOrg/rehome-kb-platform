import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import {
  getPdRequest,
  listPdRequests,
  processPdRequest,
} from "./admin-pd-requests";

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

describe("admin-pd-requests API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("no filters → clean URL", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listPdRequests();
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/personal-data/requests",
    );
  });

  it("encodes status filter", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listPdRequests({ status: "OVERDUE" });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("status=OVERDUE");
  });

  it("encodes type + cursor filters", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listPdRequests({ type: "delete", cursor: "abc123" });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("type=delete");
    expect(url).toContain("cursor=abc123");
  });

  it("returns parsed response shape", async () => {
    const fixture = {
      data: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          type: "delete",
          status: "NEW",
          subject_id: "22222222-2222-2222-2222-222222222222",
          subject_email: "user@example.com",
          subject_phone: null,
          description: "Удалите мои данные",
          assigned_to: null,
          created_at: "2026-05-01T12:00:00Z",
          due_at: "2026-05-31T12:00:00Z",
          completed_at: null,
          resolution_note: null,
        },
      ],
    };
    apiFetchMock.mockResolvedValueOnce(fixture);
    const result = await listPdRequests();
    expect(result.data).toHaveLength(1);
    expect(result.data[0].type).toBe("delete");
    expect(result.data[0].subject_email).toBe("user@example.com");
  });
});

describe("getPdRequest", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("calls expected URL", async () => {
    apiFetchMock.mockResolvedValueOnce({ id: "x" });
    await getPdRequest("abc-123");
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/personal-data/requests/abc-123",
    );
  });
});

describe("processPdRequest", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("sends PATCH with status + resolution_note", async () => {
    apiFetchMock.mockResolvedValueOnce({});
    await processPdRequest("abc", {
      status: "COMPLETED",
      resolution_note: "Все данные удалены",
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/personal-data/requests/abc",
      expect.objectContaining({
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
      }),
    );
    const call = apiFetchMock.mock.calls[0][1] as RequestInit;
    expect(call.body).toBe(
      JSON.stringify({ status: "COMPLETED", resolution_note: "Все данные удалены" }),
    );
  });

  it("supports status-only update без resolution_note", async () => {
    apiFetchMock.mockResolvedValueOnce({});
    await processPdRequest("abc", { status: "IN_PROGRESS" });
    const call = apiFetchMock.mock.calls[0][1] as RequestInit;
    expect(call.body).toBe(JSON.stringify({ status: "IN_PROGRESS" }));
  });
});

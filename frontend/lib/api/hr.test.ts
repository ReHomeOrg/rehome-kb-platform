import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { getEmployee, listEmployees } from "./hr";

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

describe("hr API", () => {
  afterEach(() => {
    apiFetchMock.mockReset();
  });

  it("listEmployees без фильтров — путь без querystring", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { cursor_next: null, has_more: false },
    });
    await listEmployees();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/hr/employees");
  });

  it("listEmployees encode'ит cursor + limit", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { cursor_next: null, has_more: false },
    });
    await listEmployees({ cursor: "abc", limit: 50 });
    const call = apiFetchMock.mock.calls[0][0] as string;
    expect(call).toContain("cursor=abc");
    expect(call).toContain("limit=50");
  });

  it("listEmployees omit'ит include_terminated по default", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { cursor_next: null, has_more: false },
    });
    await listEmployees({ include_terminated: false });
    expect(apiFetchMock.mock.calls[0][0]).toBe("/api/v1/hr/employees");
  });

  it("listEmployees добавляет include_terminated=true", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { cursor_next: null, has_more: false },
    });
    await listEmployees({ include_terminated: true });
    expect(apiFetchMock.mock.calls[0][0]).toContain("include_terminated=true");
  });

  it("getEmployee encode'ит id для URL safety", async () => {
    apiFetchMock.mockResolvedValueOnce({} as never);
    await getEmployee("uuid-with-special/chars");
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/hr/employees/uuid-with-special%2Fchars",
    );
  });
});

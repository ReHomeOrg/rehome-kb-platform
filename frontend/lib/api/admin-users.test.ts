import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { listKbUsers } from "./admin-users";

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

describe("admin-users API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("no filters → clean URL", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listKbUsers();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/admin/users");
  });

  it("encodes role + status filters", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listKbUsers({ role: "staff_admin", status: "ACTIVE" });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("role=staff_admin");
    expect(url).toContain("status=ACTIVE");
  });

  it("encodes cursor", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listKbUsers({ cursor: "abc123" });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("cursor=abc123");
  });

  it("returns parsed response shape", async () => {
    const fixture = {
      data: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          email: "admin@rehome.one",
          full_name: "Иван Админов",
          role: "staff_admin",
          permissions: [],
          status: "ACTIVE",
          created_at: "2026-01-01T00:00:00Z",
          last_login_at: "2026-05-01T12:00:00Z",
          mfa_enabled: true,
        },
      ],
    };
    apiFetchMock.mockResolvedValueOnce(fixture);
    const result = await listKbUsers();
    expect(result.data).toHaveLength(1);
    expect(result.data[0].role).toBe("staff_admin");
    expect(result.data[0].mfa_enabled).toBe(true);
  });
});

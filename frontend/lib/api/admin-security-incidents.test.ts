import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { listSecurityIncidents } from "./admin-security-incidents";

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

describe("admin-security-incidents API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("no filters → clean URL", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listSecurityIncidents();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/admin/security-incidents");
  });

  it("encodes severity filter", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listSecurityIncidents({ severity: "critical" });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("severity=critical");
  });

  it("encodes status + cursor filters", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listSecurityIncidents({ status: "OPEN", cursor: "abc123" });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("status=OPEN");
    expect(url).toContain("cursor=abc123");
  });

  it("returns parsed response shape", async () => {
    const fixture = {
      data: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          incident_type: "access_violation",
          severity: "high",
          status: "OPEN",
          detected_at: "2026-05-01T12:00:00Z",
          detected_by: "audit",
          affected_resources: [],
          rkn_notification_required: true,
          rkn_notified_at: null,
          resolution_note: null,
          resolved_at: null,
        },
      ],
    };
    apiFetchMock.mockResolvedValueOnce(fixture);
    const result = await listSecurityIncidents();
    expect(result.data).toHaveLength(1);
    expect(result.data[0].severity).toBe("high");
    expect(result.data[0].rkn_notification_required).toBe(true);
    expect(result.data[0].rkn_notified_at).toBeNull();
  });
});

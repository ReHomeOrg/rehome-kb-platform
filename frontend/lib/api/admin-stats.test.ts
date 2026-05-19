import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { getAdminStats } from "./admin-stats";

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

describe("admin-stats API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("no filters → clean URL", async () => {
    apiFetchMock.mockResolvedValueOnce({});
    await getAdminStats();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/admin/stats");
  });

  it("encodes from + to filters", async () => {
    apiFetchMock.mockResolvedValueOnce({});
    await getAdminStats({ from: "2026-05-01T00:00:00Z", to: "2026-05-31T23:59:59Z" });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("from=2026-05-01");
    expect(url).toContain("to=2026-05-31");
  });

  it("returns parsed AdminStats shape", async () => {
    const fixture = {
      period: { from: "2026-05-01T00:00:00Z", to: "2026-05-31T23:59:59Z" },
      requests: { total: 0, by_endpoint: {}, by_status: {}, error_rate_percent: 0 },
      chat: {
        sessions: 5,
        messages: 12,
        containment_rate: 0.8,
        avg_rating: null,
        no_answer_count: 0,
        escalations: 1,
      },
      content: { total_articles: 30, total_documents: 5, pending_reviews: 2 },
      security: {
        open_incidents: 0,
        critical_incidents: 0,
        overdue_pd_requests: 0,
      },
    };
    apiFetchMock.mockResolvedValueOnce(fixture);
    const result = await getAdminStats();
    expect(result.content.total_articles).toBe(30);
    expect(result.chat.containment_rate).toBe(0.8);
    expect(result.chat.avg_rating).toBeNull();
  });
});

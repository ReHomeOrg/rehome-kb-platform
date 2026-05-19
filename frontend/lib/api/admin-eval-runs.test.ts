import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { listEvalRuns } from "./admin-eval-runs";

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

describe("admin-eval-runs API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("no filters → clean URL", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listEvalRuns();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/admin/llm/eval-runs");
  });

  it("encodes provider filter в querystring", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listEvalRuns({ provider: "mock" });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("provider=mock");
  });

  it("encodes limit", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listEvalRuns({ limit: 100 });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("limit=100");
  });

  it("returns parsed response shape", async () => {
    const fixture = {
      data: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          started_at: "2026-05-01T12:00:00Z",
          completed_at: "2026-05-01T12:05:00Z",
          status: "COMPLETED",
          providers: ["mock"],
          test_set: "smoke",
          results: [
            {
              provider: "mock",
              composite_score: null,
              answer_correctness: 0.8,
              faithfulness: null,
              citation_accuracy: 0.5,
              refusal_correctness: 1.0,
              avg_latency_ms: 50,
              cost_per_query_rub: 0.0,
            },
          ],
        },
      ],
    };
    apiFetchMock.mockResolvedValueOnce(fixture);
    const result = await listEvalRuns();
    expect(result.data).toHaveLength(1);
    expect(result.data[0].providers).toEqual(["mock"]);
    expect(result.data[0].results[0].provider).toBe("mock");
    expect(result.data[0].status).toBe("COMPLETED");
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { listLlmProviders } from "./admin-llm-providers";

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

describe("admin-llm-providers API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("calls expected URL", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await listLlmProviders();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/admin/llm/providers");
  });

  it("returns parsed response shape", async () => {
    const fixture = {
      data: [
        {
          id: "mock",
          name: "Mock",
          vendor: "rehome-internal",
          model: null,
          status: "EXPERIMENTAL",
          is_current: true,
          cost_per_1m_input_tokens_rub: null,
          cost_per_1m_output_tokens_rub: null,
          max_context_tokens: null,
          supports_streaming: null,
          last_health_check: null,
          health_status: null,
        },
      ],
    };
    apiFetchMock.mockResolvedValueOnce(fixture);
    const result = await listLlmProviders();
    expect(result.data).toHaveLength(1);
    expect(result.data[0].is_current).toBe(true);
  });
});

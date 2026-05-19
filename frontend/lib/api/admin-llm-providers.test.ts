import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import {
  listLlmProviders,
  setActiveLlmProvider,
} from "./admin-llm-providers";

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

describe("setActiveLlmProvider", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("sends PUT with provider_id + reason", async () => {
    apiFetchMock.mockResolvedValueOnce({ active_provider: "gigachat" });
    await setActiveLlmProvider({ provider_id: "gigachat", reason: "A/B" });
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/llm/active",
      expect.objectContaining({ method: "PUT" }),
    );
    const call = apiFetchMock.mock.calls[0][1] as RequestInit;
    expect(call.body).toBe(
      JSON.stringify({ provider_id: "gigachat", reason: "A/B" }),
    );
    expect((call.headers as Record<string, string>)["X-MFA-Token"]).toBeUndefined();
  });

  it("attaches X-MFA-Token when provided", async () => {
    apiFetchMock.mockResolvedValueOnce({ active_provider: "x" });
    await setActiveLlmProvider({ provider_id: "x" }, "mfa-tok-123");
    const call = apiFetchMock.mock.calls[0][1] as RequestInit;
    expect((call.headers as Record<string, string>)["X-MFA-Token"]).toBe(
      "mfa-tok-123",
    );
  });
});

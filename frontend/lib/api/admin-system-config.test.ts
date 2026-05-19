import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { getSystemConfig } from "./admin-system-config";

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

describe("admin-system-config API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("calls expected URL", async () => {
    apiFetchMock.mockResolvedValueOnce({});
    await getSystemConfig();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/admin/system-config");
  });

  it("returns parsed SystemConfig shape", async () => {
    const fixture = {
      rate_limits: {
        guest_per_minute: null,
        user_per_minute: null,
        m2m_per_minute: null,
        chat_messages_per_5min: null,
      },
      feature_flags: { rag_enabled: true, metrics_enabled: true },
      llm_config: {
        active_provider: "mock",
        fallback_provider: null,
        ab_test_split_percent: null,
        max_context_tokens: null,
        temperature: null,
      },
      moderation: {
        auto_publish_threshold: null,
        require_review_for_categories: [],
      },
      webhooks: { max_retries: 5, timeout_seconds: 10 },
    };
    apiFetchMock.mockResolvedValueOnce(fixture);
    const result = await getSystemConfig();
    expect(result.llm_config.active_provider).toBe("mock");
    expect(result.feature_flags.rag_enabled).toBe(true);
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-system-config";
import * as stepUp from "@/lib/auth/step-up";
import type { SystemConfig } from "@/lib/api/types";

import SystemConfigEditForm from "./system-config-edit-form";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

const patchMock = vi.spyOn(api, "patchSystemConfig");
const stepUpMock = vi.spyOn(stepUp, "requestStepUpToken");

async function _acquireMfaToken(token: string = "mfa-token-x"): Promise<void> {
  stepUpMock.mockResolvedValueOnce(token);
  fireEvent.click(screen.getByText(/Получить MFA token/));
  await waitFor(() => {
    expect(screen.getByText(/MFA token получен ✓/)).toBeInTheDocument();
  });
}

function makeConfig(overrides: Partial<SystemConfig> = {}): SystemConfig {
  return {
    rate_limits: {
      guest_per_minute: null,
      user_per_minute: null,
      m2m_per_minute: null,
      chat_messages_per_5min: null,
    },
    feature_flags: {
      rag: true,
      webhook_worker: false,
      metrics_endpoint: true,
    },
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
    ...overrides,
  };
}

beforeEach(() => {
  refreshMock.mockReset();
  patchMock.mockReset();
  stepUpMock.mockReset();
});

afterEach(() => {
  patchMock.mockReset();
});

describe("SystemConfigEditForm", () => {
  it("renders initial values from feature_flags", () => {
    render(<SystemConfigEditForm initial={makeConfig()} />);
    expect(screen.getByLabelText("rag_enabled")).toBeChecked();
    expect(screen.getByLabelText("webhook_worker_enabled")).not.toBeChecked();
    expect(screen.getByLabelText("metrics_enabled")).toBeChecked();
  });

  it("no PATCH on no-op submit", async () => {
    render(<SystemConfigEditForm initial={makeConfig()} />);
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).not.toHaveBeenCalled();
    });
  });

  it("sends only changed feature_flag", async () => {
    patchMock.mockResolvedValueOnce(makeConfig());
    render(<SystemConfigEditForm initial={makeConfig()} />);
    fireEvent.click(screen.getByLabelText("rag_enabled"));
    await _acquireMfaToken();
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith(
        { "feature_flags.rag_enabled": false },
        "mfa-token-x",
      );
    });
    expect(refreshMock).toHaveBeenCalled();
  });

  it("sends fallback_provider change", async () => {
    patchMock.mockResolvedValueOnce(makeConfig());
    render(<SystemConfigEditForm initial={makeConfig()} />);
    fireEvent.change(screen.getByLabelText("llm_fallback_provider"), {
      target: { value: "vllm" },
    });
    await _acquireMfaToken();
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith(
        { llm_fallback_provider: "vllm" },
        "mfa-token-x",
      );
    });
  });

  it("rejects non-numeric threshold", async () => {
    render(<SystemConfigEditForm initial={makeConfig()} />);
    fireEvent.change(screen.getByLabelText("auto_publish_threshold"), {
      target: { value: "abc" },
    });
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/числом/);
    });
    expect(patchMock).not.toHaveBeenCalled();
  });

  it("attaches X-MFA-Token from step-up flow (#337)", async () => {
    patchMock.mockResolvedValueOnce(makeConfig());
    render(<SystemConfigEditForm initial={makeConfig()} />);
    fireEvent.click(screen.getByLabelText("metrics_enabled")); // diff
    await _acquireMfaToken("step-up-mfa-token");
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith(
        { "feature_flags.metrics_enabled": false },
        "step-up-mfa-token",
      );
    });
  });

  it("blocks PATCH if MFA token не acquired (#337)", async () => {
    render(<SystemConfigEditForm initial={makeConfig()} />);
    fireEvent.click(screen.getByLabelText("metrics_enabled"));
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/MFA token обязателен/);
    });
    expect(patchMock).not.toHaveBeenCalled();
  });
});

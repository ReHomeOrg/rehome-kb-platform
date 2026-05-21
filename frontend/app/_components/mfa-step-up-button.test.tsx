import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as stepUp from "@/lib/auth/step-up";

import MfaStepUpButton from "./mfa-step-up-button";

const stepUpMock = vi.spyOn(stepUp, "requestStepUpToken");

beforeEach(() => {
  stepUpMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("MfaStepUpButton", () => {
  it("renders label idle state", () => {
    render(<MfaStepUpButton onTokenAcquired={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Получить MFA token/ })).toBeInTheDocument();
  });

  it("happy path: click → calls requestStepUpToken → invokes callback", async () => {
    stepUpMock.mockResolvedValueOnce("token-abc");
    const onTokenAcquired = vi.fn();
    render(<MfaStepUpButton onTokenAcquired={onTokenAcquired} />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => {
      expect(onTokenAcquired).toHaveBeenCalledWith("token-abc");
    });
  });

  it("shows ✓ state when hasToken=true", () => {
    render(<MfaStepUpButton onTokenAcquired={vi.fn()} hasToken={true} />);
    expect(screen.getByRole("button", { name: /MFA token получен ✓/ })).toBeInTheDocument();
  });

  it("displays error при StepUpError из step-up flow", async () => {
    stepUpMock.mockRejectedValueOnce(new stepUp.StepUpError("Popup blocked"));
    render(<MfaStepUpButton onTokenAcquired={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Popup blocked/);
    });
  });

  it("disables button during request", async () => {
    let resolveStep: (v: string) => void = () => {};
    stepUpMock.mockReturnValueOnce(
      new Promise((res) => {
        resolveStep = res;
      }),
    );
    render(<MfaStepUpButton onTokenAcquired={vi.fn()} />);
    const btn = screen.getByRole("button") as HTMLButtonElement;
    fireEvent.click(btn);
    await waitFor(() => {
      expect(btn.disabled).toBe(true);
      expect(btn.textContent).toMatch(/Открываем Keycloak/);
    });
    resolveStep("token");
    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });
  });

  it("ignores double click while requesting", async () => {
    let resolveStep: (v: string) => void = () => {};
    stepUpMock.mockReturnValueOnce(
      new Promise((res) => {
        resolveStep = res;
      }),
    );
    render(<MfaStepUpButton onTokenAcquired={vi.fn()} />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    fireEvent.click(btn); // 2nd click ignored
    await waitFor(() => {
      expect(stepUpMock).toHaveBeenCalledTimes(1);
    });
    resolveStep("token");
  });
});

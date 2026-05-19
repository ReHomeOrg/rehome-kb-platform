import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-llm-providers";

import SwitchProviderButton from "./switch-provider-button";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

const setActiveMock = vi.spyOn(api, "setActiveLlmProvider");

beforeEach(() => {
  refreshMock.mockReset();
  setActiveMock.mockReset();
});

afterEach(() => {
  setActiveMock.mockReset();
});

describe("SwitchProviderButton", () => {
  it("renders compact Switch button by default", () => {
    render(<SwitchProviderButton providerId="gigachat" />);
    expect(screen.getByText("Switch")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Switch reason/)).not.toBeInTheDocument();
  });

  it("opens form on click", () => {
    render(<SwitchProviderButton providerId="gigachat" />);
    fireEvent.click(screen.getByText("Switch"));
    expect(screen.getByLabelText("Switch reason")).toBeInTheDocument();
    expect(screen.getByLabelText("MFA token")).toBeInTheDocument();
  });

  it("blocks submit without reason", async () => {
    render(<SwitchProviderButton providerId="gigachat" />);
    fireEvent.click(screen.getByText("Switch"));
    fireEvent.click(screen.getByText("Подтвердить"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Reason обязателен/);
    });
    expect(setActiveMock).not.toHaveBeenCalled();
  });

  it("submits PUT with reason + optional MFA token", async () => {
    setActiveMock.mockResolvedValueOnce({ active_provider: "gigachat" });
    render(<SwitchProviderButton providerId="gigachat" />);
    fireEvent.click(screen.getByText("Switch"));
    fireEvent.change(screen.getByLabelText("Switch reason"), {
      target: { value: "A/B test" },
    });
    fireEvent.change(screen.getByLabelText("MFA token"), {
      target: { value: "mfa-x" },
    });
    fireEvent.click(screen.getByText("Подтвердить"));
    await waitFor(() => {
      expect(setActiveMock).toHaveBeenCalledWith(
        { provider_id: "gigachat", reason: "A/B test" },
        "mfa-x",
      );
    });
    expect(refreshMock).toHaveBeenCalled();
  });

  it("cancel returns to compact button", () => {
    render(<SwitchProviderButton providerId="gigachat" />);
    fireEvent.click(screen.getByText("Switch"));
    fireEvent.click(screen.getByText("Отмена"));
    expect(screen.queryByLabelText(/Switch reason/)).not.toBeInTheDocument();
  });
});

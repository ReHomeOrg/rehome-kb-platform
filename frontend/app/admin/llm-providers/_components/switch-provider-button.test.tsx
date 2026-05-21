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
    // Step-up MFA button (#337) replaces manual input.
    expect(screen.getByText(/Получить MFA token/)).toBeInTheDocument();
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

  it("blocks submit без MFA token (step-up required #337)", async () => {
    render(<SwitchProviderButton providerId="gigachat" />);
    fireEvent.click(screen.getByText("Switch"));
    fireEvent.change(screen.getByLabelText("Switch reason"), {
      target: { value: "A/B test" },
    });
    fireEvent.click(screen.getByText("Подтвердить"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/MFA token обязателен/);
    });
    expect(setActiveMock).not.toHaveBeenCalled();
  });

  it("cancel returns to compact button", () => {
    render(<SwitchProviderButton providerId="gigachat" />);
    fireEvent.click(screen.getByText("Switch"));
    fireEvent.click(screen.getByText("Отмена"));
    expect(screen.queryByLabelText(/Switch reason/)).not.toBeInTheDocument();
  });
});

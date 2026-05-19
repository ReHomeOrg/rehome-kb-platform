import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-eval-runs";
import { ApiError } from "@/lib/api/client";

import StartRunForm from "./start-run-form";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

const startMock = vi.spyOn(api, "startEvalRun");

beforeEach(() => {
  refreshMock.mockReset();
  startMock.mockReset();
});

afterEach(() => {
  startMock.mockReset();
});

describe("StartRunForm", () => {
  it("renders provider checkboxes + test_set radios with mock+smoke default", () => {
    render(<StartRunForm />);
    expect(screen.getByLabelText("Provider mock")).toBeChecked();
    expect(screen.getByLabelText("Test set smoke")).toBeChecked();
  });

  it("toggle provider checkbox", () => {
    render(<StartRunForm />);
    const mockBox = screen.getByLabelText("Provider mock") as HTMLInputElement;
    fireEvent.click(mockBox);
    expect(mockBox.checked).toBe(false);
  });

  it("blocks submit when no providers selected", async () => {
    render(<StartRunForm />);
    fireEvent.click(screen.getByLabelText("Provider mock")); // uncheck default
    fireEvent.click(screen.getByText("Запустить"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/один provider/);
    });
    expect(startMock).not.toHaveBeenCalled();
  });

  it("submits providers + test_set", async () => {
    startMock.mockResolvedValueOnce({ run_id: "abc12345-1234-1234-1234-123456789012" });
    render(<StartRunForm />);
    fireEvent.click(screen.getByText("Запустить"));
    await waitFor(() => {
      expect(startMock).toHaveBeenCalledWith({
        providers: ["mock"],
        test_set: "smoke",
      });
    });
    expect(refreshMock).toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(/abc12345/);
  });

  it("shows error from backend ApiError", async () => {
    startMock.mockRejectedValueOnce(
      new ApiError(422, { detail: "Unsupported provider" }, "Unsupported provider"),
    );
    render(<StartRunForm />);
    fireEvent.click(screen.getByText("Запустить"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/422/);
    });
  });

  it("changing test_set updates state", () => {
    render(<StartRunForm />);
    fireEvent.click(screen.getByLabelText("Test set full"));
    const full = screen.getByLabelText("Test set full") as HTMLInputElement;
    expect(full.checked).toBe(true);
  });
});

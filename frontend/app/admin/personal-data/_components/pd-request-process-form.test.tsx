import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-pd-requests";
import type { PersonalDataRequest } from "@/lib/api/types";

import PdRequestProcessForm from "./pd-request-process-form";

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

const processMock = vi.spyOn(api, "processPdRequest");

function makeRequest(overrides: Partial<PersonalDataRequest> = {}): PersonalDataRequest {
  return {
    id: "req-abc",
    type: "delete",
    status: "NEW",
    subject_id: "subj-1",
    subject_email: "user@example.com",
    subject_phone: null,
    description: "Удалите мои данные",
    assigned_to: null,
    created_at: "2026-05-01T00:00:00Z",
    due_at: "2026-05-31T00:00:00Z",
    completed_at: null,
    resolution_note: null,
    ...overrides,
  };
}

beforeEach(() => {
  pushMock.mockReset();
  refreshMock.mockReset();
  processMock.mockReset();
});

afterEach(() => {
  processMock.mockReset();
});

describe("PdRequestProcessForm", () => {
  it("renders subject info + default status IN_PROGRESS for NEW", () => {
    render(<PdRequestProcessForm initial={makeRequest()} />);
    expect(screen.getByText("user@example.com")).toBeInTheDocument();
    const select = screen.getByLabelText(/Process status/) as HTMLSelectElement;
    expect(select.value).toBe("IN_PROGRESS");
  });

  it("highlights overdue when due_at in past", () => {
    render(
      <PdRequestProcessForm
        initial={makeRequest({
          status: "IN_PROGRESS",
          due_at: "2025-01-01T00:00:00Z",
        })}
      />,
    );
    expect(screen.getByText(/просрочено/)).toBeInTheDocument();
  });

  it("submits PATCH with status + resolution_note", async () => {
    processMock.mockResolvedValueOnce(makeRequest({ status: "COMPLETED" }));
    render(<PdRequestProcessForm initial={makeRequest()} />);
    fireEvent.change(screen.getByLabelText(/Process status/), {
      target: { value: "COMPLETED" },
    });
    fireEvent.change(screen.getByLabelText(/Resolution note/), {
      target: { value: "Данные удалены" },
    });
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(processMock).toHaveBeenCalledWith("req-abc", {
        status: "COMPLETED",
        resolution_note: "Данные удалены",
      });
    });
    expect(pushMock).toHaveBeenCalledWith("/admin/personal-data");
  });

  it("submits without resolution_note if unchanged from null", async () => {
    processMock.mockResolvedValueOnce(makeRequest({ status: "IN_PROGRESS" }));
    render(<PdRequestProcessForm initial={makeRequest()} />);
    // Only status (defaults IN_PROGRESS, нужно прокликать чтобы было видно изменение)
    fireEvent.change(screen.getByLabelText(/Process status/), {
      target: { value: "REJECTED" },
    });
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(processMock).toHaveBeenCalledWith("req-abc", { status: "REJECTED" });
    });
  });
});

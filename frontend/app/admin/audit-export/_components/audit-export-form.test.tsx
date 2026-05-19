import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-audit-export";

import AuditExportForm from "./audit-export-form";

const startMock = vi.spyOn(api, "startAuditExport");

beforeEach(() => {
  startMock.mockReset();
});

afterEach(() => {
  startMock.mockReset();
});

describe("AuditExportForm", () => {
  it("renders default dates + reason input", () => {
    render(<AuditExportForm />);
    expect(screen.getByLabelText(/From datetime/)).toBeInTheDocument();
    expect(screen.getByLabelText(/To datetime/)).toBeInTheDocument();
    expect(screen.getByLabelText("Reason")).toBeInTheDocument();
  });

  it("blocks submit without reason", async () => {
    render(<AuditExportForm />);
    fireEvent.click(screen.getByText("Запустить export"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Reason обязателен/);
    });
    expect(startMock).not.toHaveBeenCalled();
  });

  it("submits with required + filters when provided", async () => {
    startMock.mockResolvedValueOnce({
      task_id: "task-1",
      estimated_ready_at: null,
    });
    render(<AuditExportForm />);
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Запрос РКН №42" },
    });
    fireEvent.change(screen.getByLabelText(/actor_sub/), {
      target: { value: "user-uuid" },
    });
    fireEvent.click(screen.getByText("Запустить export"));
    await waitFor(() => {
      expect(startMock).toHaveBeenCalled();
    });
    const arg = startMock.mock.calls[0][0];
    expect(arg.reason).toBe("Запрос РКН №42");
    expect(arg.filters).toEqual({ actor_sub: "user-uuid" });
    expect(screen.getByRole("status")).toHaveTextContent(/task-1/);
  });

  it("omits filters object when all empty", async () => {
    startMock.mockResolvedValueOnce({ task_id: "x", estimated_ready_at: null });
    render(<AuditExportForm />);
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Reason" },
    });
    fireEvent.click(screen.getByText("Запустить export"));
    await waitFor(() => {
      expect(startMock).toHaveBeenCalled();
    });
    expect(startMock.mock.calls[0][0].filters).toBeUndefined();
  });
});

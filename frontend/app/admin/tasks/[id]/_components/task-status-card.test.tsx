import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-tasks";
import type { AdminTaskStatusView } from "@/lib/api/types";

import TaskStatusCard from "./task-status-card";

const getMock = vi.spyOn(api, "getAdminTask");

function makeTask(overrides: Partial<AdminTaskStatusView> = {}): AdminTaskStatusView {
  return {
    task_id: "task-abc",
    type: "reindex",
    status: "RUNNING",
    progress_percent: 0,
    created_at: "2026-05-01T12:00:00Z",
    completed_at: null,
    result_url: null,
    error: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  getMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  getMock.mockReset();
});

describe("TaskStatusCard", () => {
  it("renders initial state correctly (RUNNING)", () => {
    render(<TaskStatusCard initial={makeTask()} />);
    expect(screen.getByText("task-abc")).toBeInTheDocument();
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByLabelText("Polling status")).toBeInTheDocument();
  });

  it("does NOT poll if initial is terminal (COMPLETED)", () => {
    render(<TaskStatusCard initial={makeTask({ status: "COMPLETED" })} />);
    expect(screen.queryByLabelText("Polling status")).not.toBeInTheDocument();
    expect(screen.getByText(/Polling завершён/)).toBeInTheDocument();
  });

  it("polls + updates state when status changes", async () => {
    const completed = makeTask({
      status: "COMPLETED",
      progress_percent: 100,
      completed_at: "2026-05-01T12:05:00Z",
    });
    getMock.mockResolvedValueOnce(completed);

    render(<TaskStatusCard initial={makeTask({ status: "RUNNING" })} />);
    expect(screen.getByText("RUNNING")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(3000);
      // Wait for async resolution.
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getMock).toHaveBeenCalledWith("task-abc");
    // Status updated → polling element removed.
    expect(screen.queryByText("RUNNING")).not.toBeInTheDocument();
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
  });

  it("renders result_url as link when present", () => {
    render(
      <TaskStatusCard
        initial={makeTask({
          status: "COMPLETED",
          result_url: "/api/v1/audit-log/export.csv?since=...",
        })}
      />,
    );
    const link = screen.getByText("/api/v1/audit-log/export.csv?since=...");
    expect(link.tagName).toBe("A");
  });

  it("renders error when set", () => {
    render(
      <TaskStatusCard
        initial={makeTask({
          status: "FAILED",
          error: "Embedding provider timeout",
        })}
      />,
    );
    expect(screen.getByText(/Embedding provider timeout/)).toBeInTheDocument();
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-maintenance";

import CacheInvalidateButton from "./cache-invalidate-button";
import ReindexButton from "./reindex-button";

const reindexMock = vi.spyOn(api, "triggerReindex");
const invalidateMock = vi.spyOn(api, "invalidateCache");
let confirmSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  reindexMock.mockReset();
  invalidateMock.mockReset();
  confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  confirmSpy.mockRestore();
});

describe("ReindexButton", () => {
  it("default scope=articles + button triggers POST", async () => {
    reindexMock.mockResolvedValueOnce({ task_id: "task-123" });
    render(<ReindexButton />);
    fireEvent.click(screen.getByText("Запустить reindex"));
    await waitFor(() => {
      expect(reindexMock).toHaveBeenCalledWith("articles");
    });
    expect(screen.getByRole("status")).toHaveTextContent(/task-123/);
  });

  it("abort if user cancels confirm", async () => {
    confirmSpy.mockReturnValue(false);
    render(<ReindexButton />);
    fireEvent.click(screen.getByText("Запустить reindex"));
    expect(reindexMock).not.toHaveBeenCalled();
  });

  it("scope change reflects in API call", async () => {
    reindexMock.mockResolvedValueOnce({ task_id: "x" });
    render(<ReindexButton />);
    fireEvent.change(screen.getByLabelText(/Reindex scope/), {
      target: { value: "documents" },
    });
    fireEvent.click(screen.getByText("Запустить reindex"));
    await waitFor(() => {
      expect(reindexMock).toHaveBeenCalledWith("documents");
    });
  });
});

describe("CacheInvalidateButton", () => {
  it("default scope=all + button triggers DELETE", async () => {
    invalidateMock.mockResolvedValueOnce({ status: "accepted", scope: "all" });
    render(<CacheInvalidateButton />);
    fireEvent.click(screen.getByText("Инвалидировать кеш"));
    await waitFor(() => {
      expect(invalidateMock).toHaveBeenCalledWith("all");
    });
    expect(screen.getByRole("status")).toHaveTextContent(/accepted.*all/);
  });

  it("abort if user cancels confirm", async () => {
    confirmSpy.mockReturnValue(false);
    render(<CacheInvalidateButton />);
    fireEvent.click(screen.getByText("Инвалидировать кеш"));
    expect(invalidateMock).not.toHaveBeenCalled();
  });
});

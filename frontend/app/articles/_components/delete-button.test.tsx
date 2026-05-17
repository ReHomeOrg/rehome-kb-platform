import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DeleteArticleButton from "./delete-button";

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  pushMock.mockReset();
  refreshMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

describe("DeleteArticleButton", () => {
  it("свёрнутое состояние показывает Удалить", () => {
    render(<DeleteArticleButton slug="onboarding-guide" />);
    expect(screen.getByRole("button", { name: "Удалить" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Подтвердить" })).toBeNull();
  });

  it("click открывает confirm panel", () => {
    render(<DeleteArticleButton slug="onboarding-guide" />);
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
    expect(
      screen.getByText(/soft-deleted/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Подтвердить" }),
    ).toBeInTheDocument();
  });

  it("confirm → DELETE + push('/articles')", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<DeleteArticleButton slug="onboarding-guide" />);
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/articles/onboarding-guide",
        expect.objectContaining({ method: "DELETE" }),
      );
    });
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/articles");
    });
  });

  it("Отмена возвращает в свёрнутое состояние без fetch", () => {
    render(<DeleteArticleButton slug="onboarding-guide" />);
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.getByRole("button", { name: "Удалить" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("backend 403 (insufficient scope) → отображает status без redirect", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Forbidden" }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<DeleteArticleButton slug="onboarding-guide" />);
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/403/);
    });
    expect(pushMock).not.toHaveBeenCalled();
  });
});

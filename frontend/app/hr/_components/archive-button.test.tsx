import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ArchiveButton from "./archive-button";

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

describe("ArchiveButton", () => {
  it("показывает Архивировать в свёрнутом состоянии", () => {
    render(<ArchiveButton id="emp-1" />);
    expect(
      screen.getByRole("button", { name: "Архивировать" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Подтвердить архивацию/)).toBeNull();
  });

  it("click открывает confirm panel с warning", () => {
    render(<ArchiveButton id="emp-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Архивировать" }));
    expect(screen.getByText(/Данные сохраняются 50 лет/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Подтвердить архивацию" }),
    ).toBeInTheDocument();
  });

  it("Отмена возвращает в свёрнутое состояние", () => {
    render(<ArchiveButton id="emp-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Архивировать" }));
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(
      screen.getByRole("button", { name: "Архивировать" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Подтвердить архивацию/)).toBeNull();
  });

  it("confirm → DELETE + push('/hr')", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<ArchiveButton id="emp-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Архивировать" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить архивацию" }),
    );
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/hr/employees/emp-1",
        expect.objectContaining({ method: "DELETE" }),
      );
    });
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/hr");
    });
  });

  it("backend 404 → отображает status + не редиректит", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Employee not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<ArchiveButton id="emp-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Архивировать" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить архивацию" }),
    );
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/404/);
    });
    expect(pushMock).not.toHaveBeenCalled();
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PortalAccessControl from "./portal-access-control";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  refreshMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

describe("PortalAccessControl", () => {
  it("показывает текущий уровень в caption", () => {
    render(<PortalAccessControl id="c-1" current="LIGHT" />);
    expect(screen.getByText(/Текущий уровень/)).toBeInTheDocument();
    // Текущий level — в select по умолчанию.
    const select = screen.getByLabelText(/Новый уровень/) as HTMLSelectElement;
    expect(select.value).toBe("LIGHT");
  });

  it("кнопка disabled когда target == current (Без изменений)", () => {
    render(<PortalAccessControl id="c-1" current="LIGHT" />);
    const button = screen.getByRole("button", { name: /Без изменений/ });
    expect(button).toBeDisabled();
  });

  it("повышение NONE→FULL без reason → local error", async () => {
    render(<PortalAccessControl id="c-1" current="NONE" />);
    fireEvent.change(screen.getByLabelText(/Новый уровень/), {
      target: { value: "FULL" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Применить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Reason обязательна/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("повышение с reason → PUT /portal-access + refresh", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ id: "c-1", portal_access_level: "FULL" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<PortalAccessControl id="c-1" current="NONE" />);
    fireEvent.change(screen.getByLabelText(/Новый уровень/), {
      target: { value: "LIGHT" },
    });
    fireEvent.change(screen.getByLabelText(/Причина/), {
      target: { value: "Подписан расширенный SLA" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Применить/ }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/collaborators/c-1/portal-access",
        expect.objectContaining({ method: "PUT" }),
      );
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body).toEqual({
      portal_access_level: "LIGHT",
      reason: "Подписан расширенный SLA",
    });
    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalled();
    });
  });

  it("понижение FULL→LIGHT без reason → PUT с reason=null", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ id: "c-1", portal_access_level: "LIGHT" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<PortalAccessControl id="c-1" current="FULL" />);
    fireEvent.change(screen.getByLabelText(/Новый уровень/), {
      target: { value: "LIGHT" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Применить/ }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body).toEqual({
      portal_access_level: "LIGHT",
      reason: null,
    });
  });

  it("backend 409 на повышение → отображает status + detail", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "FULL требует подписания SLA" }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<PortalAccessControl id="c-1" current="LIGHT" />);
    fireEvent.change(screen.getByLabelText(/Новый уровень/), {
      target: { value: "FULL" },
    });
    fireEvent.change(screen.getByLabelText(/Причина/), {
      target: { value: "Test" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Применить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /409: FULL требует подписания SLA/,
      );
    });
    expect(refreshMock).not.toHaveBeenCalled();
  });
});

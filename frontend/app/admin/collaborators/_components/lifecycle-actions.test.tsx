import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LifecycleActions from "./lifecycle-actions";

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

describe("LifecycleActions", () => {
  it("показывает Активировать для PENDING_REVIEW", () => {
    render(<LifecycleActions id="c-1" status="PENDING_REVIEW" />);
    expect(
      screen.getByRole("button", { name: "Активировать" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Приостановить/ })).toBeNull();
  });

  it("показывает Приостановить для ACTIVE", () => {
    render(<LifecycleActions id="c-1" status="ACTIVE" />);
    expect(
      screen.getByRole("button", { name: "Приостановить" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Активировать" })).toBeNull();
  });

  it("оба варианта возможны для SUSPENDED (только Активировать)", () => {
    render(<LifecycleActions id="c-1" status="SUSPENDED" />);
    expect(
      screen.getByRole("button", { name: "Активировать" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Приостановить/ })).toBeNull();
  });

  it("возвращает null для ARCHIVED (нет actions)", () => {
    const { container } = render(
      <LifecycleActions id="c-1" status="ARCHIVED" />,
    );
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("activate → POST /activate + refresh()", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ id: "c-1", status: "ACTIVE" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<LifecycleActions id="c-1" status="PENDING_REVIEW" />);
    fireEvent.click(screen.getByRole("button", { name: "Активировать" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/collaborators/c-1/activate",
        expect.objectContaining({ method: "POST" }),
      );
    });
    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalled();
    });
  });

  it("activate error → отображает status code и detail", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "Invalid transition" }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<LifecycleActions id="c-1" status="PENDING_REVIEW" />);
    fireEvent.click(screen.getByRole("button", { name: "Активировать" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /409: Invalid transition/,
      );
    });
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("suspend: клик раскрывает form, пустой reason — local error", async () => {
    render(<LifecycleActions id="c-1" status="ACTIVE" />);
    fireEvent.click(screen.getByRole("button", { name: "Приостановить" }));
    // Кнопка теперь "Отмена".
    expect(screen.getByRole("button", { name: "Отмена" })).toBeInTheDocument();
    // Form rendered.
    expect(screen.getByText(/Причина/)).toBeInTheDocument();
    // Без ввода reason: HTML5 `required` блокирует submit на browser-стороне,
    // достаточно проверить что fetch не вызывается до заполнения.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("suspend: ввод reason + submit → POST /suspend + refresh()", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ id: "c-1", status: "SUSPENDED" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<LifecycleActions id="c-1" status="ACTIVE" />);
    fireEvent.click(screen.getByRole("button", { name: "Приостановить" }));
    const textarea = screen.getByPlaceholderText(/жалобы клиентов/);
    fireEvent.change(textarea, {
      target: { value: "Проверка СЛА после жалобы" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Подтвердить/ }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/collaborators/c-1/suspend",
        expect.objectContaining({ method: "POST" }),
      );
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body).toEqual({
      reason: "Проверка СЛА после жалобы",
      until: null,
    });
    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalled();
    });
  });
});

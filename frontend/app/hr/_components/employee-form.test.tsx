import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HrEmployee } from "@/lib/api/types";

import EmployeeForm from "./employee-form";

const pushMock = vi.fn();
const refreshMock = vi.fn();
const backMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock, back: backMock }),
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

function fillRequired(): void {
  fireEvent.change(screen.getByLabelText(/ФИО/), {
    target: { value: "Иванов И.И." },
  });
  fireEvent.change(screen.getByLabelText(/Должность/), {
    target: { value: "Менеджер" },
  });
  fireEvent.change(screen.getByLabelText(/Дата приёма/), {
    target: { value: "2026-01-15" },
  });
}

function employeeFixture(): HrEmployee {
  return {
    id: "emp-1",
    full_name: "Петров П.П.",
    position: "Разработчик",
    department: "IT",
    hire_date: "2025-08-01",
    status: "ACTIVE",
    updated_at: "2026-05-17T12:00:00Z",
    user_id: null,
    personnel_number: "T-042",
    termination_date: null,
    contact_info: { phone: "+7..." },
    notes: {},
    created_at: "2025-08-01T00:00:00Z",
    archived_at: null,
  };
}

describe("EmployeeForm (create)", () => {
  it("показывает кнопку Создать в режиме create", () => {
    render(<EmployeeForm />);
    expect(screen.getByRole("button", { name: "Создать" })).toBeInTheDocument();
  });

  it("happy path → POST /hr/employees + navigation", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "new-emp", full_name: "Иванов И.И." }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<EmployeeForm />);
    fillRequired();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/hr/employees",
        expect.objectContaining({ method: "POST" }),
      );
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body.full_name).toBe("Иванов И.И.");
    expect(body.position).toBe("Менеджер");
    expect(body.hire_date).toBe("2026-01-15");
    expect(body.status).toBe("ACTIVE");
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/hr/new-emp");
    });
  });

  it("TERMINATED без termination_date → local error", async () => {
    render(<EmployeeForm />);
    fillRequired();
    fireEvent.change(screen.getByLabelText(/Статус/), {
      target: { value: "TERMINATED" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /дату увольнения/,
      );
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("backend 422 → отображает status code и detail", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Invalid hire_date" }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<EmployeeForm />);
    fillRequired();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /422: Invalid hire_date/,
      );
    });
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("невалидный JSON в notes → local error без fetch", async () => {
    render(<EmployeeForm />);
    fillRequired();
    fireEvent.change(screen.getByLabelText(/Заметки HR/), {
      target: { value: "{not json}" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/notes:/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("EmployeeForm (edit)", () => {
  it("в режиме edit показывает Сохранить + initial values", () => {
    render(<EmployeeForm initial={employeeFixture()} />);
    expect(
      screen.getByRole("button", { name: "Сохранить" }),
    ).toBeInTheDocument();
    expect((screen.getByLabelText(/ФИО/) as HTMLInputElement).value).toBe(
      "Петров П.П.",
    );
    expect(
      (screen.getByLabelText(/Должность/) as HTMLInputElement).value,
    ).toBe("Разработчик");
  });

  it("happy edit → PATCH /hr/employees/{id}", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "emp-1", full_name: "Петров П.П." }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<EmployeeForm initial={employeeFixture()} />);
    fireEvent.change(screen.getByLabelText(/Должность/), {
      target: { value: "Старший разработчик" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/hr/employees/emp-1",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body.position).toBe("Старший разработчик");
    expect(body.full_name).toBe("Петров П.П.");
  });
});

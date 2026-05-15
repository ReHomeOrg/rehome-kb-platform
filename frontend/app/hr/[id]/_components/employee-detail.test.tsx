import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HrEmployee } from "@/lib/api/types";

import EmployeeDetail from "./employee-detail";

function _emp(over: Partial<HrEmployee> = {}): HrEmployee {
  return {
    id: "emp-1",
    full_name: "Иван Иванов",
    position: "Менеджер",
    department: "Аренда",
    hire_date: "2026-01-15",
    status: "ACTIVE",
    updated_at: "2026-05-15T00:00:00Z",
    user_id: null,
    personnel_number: "T-0042",
    termination_date: null,
    contact_info: {},
    notes: {},
    created_at: "2026-01-15T00:00:00Z",
    archived_at: null,
    ...over,
  };
}

describe("EmployeeDetail", () => {
  it("renders full_name + position", () => {
    render(<EmployeeDetail employee={_emp()} />);
    expect(screen.getByText("Иван Иванов")).toBeInTheDocument();
    expect(screen.getByText("Менеджер")).toBeInTheDocument();
  });

  it("renders department когда задан", () => {
    render(<EmployeeDetail employee={_emp({ department: "Аренда" })} />);
    expect(screen.getByText("Аренда")).toBeInTheDocument();
  });

  it("renders dash для null department", () => {
    render(<EmployeeDetail employee={_emp({ department: null })} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders personnel_number когда задан", () => {
    render(<EmployeeDetail employee={_emp({ personnel_number: "T-0042" })} />);
    expect(screen.getByText("T-0042")).toBeInTheDocument();
  });

  it("hides termination block для ACTIVE статуса", () => {
    render(
      <EmployeeDetail employee={_emp({ status: "ACTIVE", termination_date: null })} />,
    );
    expect(screen.queryByText("Уволен")).not.toBeInTheDocument();
  });

  it("renders termination_date для TERMINATED статуса", () => {
    render(
      <EmployeeDetail
        employee={_emp({ status: "TERMINATED", termination_date: "2026-05-01" })}
      />,
    );
    // "Уволен" появляется в двух местах (label "dt Уволен" + status "Уволен")
    // — оба указывают на TERMINATED state.
    expect(screen.getAllByText("Уволен").length).toBeGreaterThanOrEqual(1);
    // Дата уволнения parsed ru-RU как `01.05.2026`.
    expect(screen.getByText("01.05.2026")).toBeInTheDocument();
  });

  it("renders status label по-русски", () => {
    render(<EmployeeDetail employee={_emp({ status: "ON_LEAVE" })} />);
    expect(screen.getByText("В отпуске")).toBeInTheDocument();
  });

  it("hides Контакты section когда contact_info пуст", () => {
    render(<EmployeeDetail employee={_emp({ contact_info: {} })} />);
    expect(screen.queryByText("Контакты")).not.toBeInTheDocument();
  });

  it("renders contact_info entries", () => {
    render(
      <EmployeeDetail
        employee={_emp({ contact_info: { phone: "+79991234567", email: "ivan@example.com" } })}
      />,
    );
    expect(screen.getByText("Контакты")).toBeInTheDocument();
    expect(screen.getByText("+79991234567")).toBeInTheDocument();
    expect(screen.getByText("ivan@example.com")).toBeInTheDocument();
  });

  it("hides notes section когда notes пусты", () => {
    render(<EmployeeDetail employee={_emp({ notes: {} })} />);
    expect(screen.queryByText("Внутренние заметки HR")).not.toBeInTheDocument();
  });

  it("renders notes section с HR sensitive flag", () => {
    render(
      <EmployeeDetail employee={_emp({ notes: { performance: "Senior level" } })} />,
    );
    expect(screen.getByText("Внутренние заметки HR")).toBeInTheDocument();
    expect(screen.getByText(/Senior level/)).toBeInTheDocument();
  });

  it("renders audit notice (ФЗ-152)", () => {
    render(<EmployeeDetail employee={_emp()} />);
    expect(screen.getByText(/ФЗ-152/)).toBeInTheDocument();
  });
});

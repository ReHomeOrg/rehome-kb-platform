import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HrEmployeeSummary } from "@/lib/api/types";

import EmployeeList from "./employee-list";

function _emp(over: Partial<HrEmployeeSummary> = {}): HrEmployeeSummary {
  return {
    id: "id-1",
    full_name: "Иванов И.И.",
    position: "QA",
    department: "Engineering",
    hire_date: "2024-01-15",
    status: "ACTIVE",
    updated_at: "2024-01-15T00:00:00Z",
    ...over,
  };
}

describe("EmployeeList", () => {
  it("empty list shows 'не найдены'", () => {
    render(
      <EmployeeList
        data={[]}
        pagination={{ cursor_next: null, has_more: false }}
        currentParamsString=""
      />,
    );
    expect(screen.getByText(/не найдены/i)).toBeInTheDocument();
  });

  it("renders employee row с правильным detail link", () => {
    render(
      <EmployeeList
        data={[_emp({ id: "abc-123" })]}
        pagination={{ cursor_next: null, has_more: false }}
        currentParamsString=""
      />,
    );
    const link = screen.getByRole("link", { name: /Иванов/i });
    expect(link.getAttribute("href")).toBe("/hr/abc-123");
  });

  it("ACTIVE status renders с зелёным бейджем", () => {
    render(
      <EmployeeList
        data={[_emp({ status: "ACTIVE" })]}
        pagination={{ cursor_next: null, has_more: false }}
        currentParamsString=""
      />,
    );
    expect(screen.getByText("Активен")).toBeInTheDocument();
  });

  it("TERMINATED renders с серым label'ом", () => {
    render(
      <EmployeeList
        data={[_emp({ status: "TERMINATED" })]}
        pagination={{ cursor_next: null, has_more: false }}
        currentParamsString=""
      />,
    );
    expect(screen.getByText("Уволен")).toBeInTheDocument();
  });

  it("показывает next-page link когда has_more+cursor", () => {
    render(
      <EmployeeList
        data={[_emp()]}
        pagination={{ cursor_next: "next-cursor", has_more: true }}
        currentParamsString="include_terminated=true"
      />,
    );
    const next = screen.getByRole("link", { name: /следующая страница/i });
    expect(next.getAttribute("href")).toBe(
      "/hr?include_terminated=true&cursor=next-cursor",
    );
  });

  it("no department renders '—'", () => {
    render(
      <EmployeeList
        data={[_emp({ department: null })]}
        pagination={{ cursor_next: null, has_more: false }}
        currentParamsString=""
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

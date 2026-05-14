import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PremisesSummary } from "@/lib/api/types";

import PremisesList from "./premises-list";

function _premises(over: Partial<PremisesSummary> = {}): PremisesSummary {
  return {
    id: "id-1",
    slug: "spb-001",
    status: "PUBLISHED",
    address: "ул. Тест 1",
    postal_code: "190000",
    cadastral_number: "78:14:0000000:0001",
    updated_at: "2024-01-15T00:00:00Z",
    ...over,
  };
}

describe("PremisesList", () => {
  it("empty list shows placeholder", () => {
    render(
      <PremisesList
        data={[]}
        pagination={{ cursor_next: null, has_more: false }}
      />,
    );
    expect(screen.getByText(/не найдены/i)).toBeInTheDocument();
  });

  it("renders address as detail link", () => {
    render(
      <PremisesList
        data={[_premises({ slug: "my-slug", address: "ул. Лесная 5" })]}
        pagination={{ cursor_next: null, has_more: false }}
      />,
    );
    const link = screen.getByRole("link", { name: /Лесная/i });
    expect(link.getAttribute("href")).toBe("/premises/my-slug");
  });

  it("PUBLISHED status — Опубликована label", () => {
    render(
      <PremisesList
        data={[_premises({ status: "PUBLISHED" })]}
        pagination={{ cursor_next: null, has_more: false }}
      />,
    );
    expect(screen.getByText("Опубликована")).toBeInTheDocument();
  });

  it("RENTED status — Сдаётся label", () => {
    render(
      <PremisesList
        data={[_premises({ status: "RENTED" })]}
        pagination={{ cursor_next: null, has_more: false }}
      />,
    );
    expect(screen.getByText("Сдаётся")).toBeInTheDocument();
  });

  it("no postal/cadastral renders '—'", () => {
    render(
      <PremisesList
        data={[_premises({ postal_code: null, cadastral_number: null })]}
        pagination={{ cursor_next: null, has_more: false }}
      />,
    );
    expect(screen.getAllByText("—").length).toBe(2);
  });

  it("next page link при has_more+cursor", () => {
    render(
      <PremisesList
        data={[_premises()]}
        pagination={{ cursor_next: "next-cursor-value", has_more: true }}
      />,
    );
    const next = screen.getByRole("link", { name: /следующая страница/i });
    expect(next.getAttribute("href")).toBe("/premises?cursor=next-cursor-value");
  });
});

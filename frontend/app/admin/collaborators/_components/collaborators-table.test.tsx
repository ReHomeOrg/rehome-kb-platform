import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CollaboratorInternal, CollaboratorPublic } from "@/lib/api/types";

import CollaboratorsTable from "./collaborators-table";

function publicFixture(
  override: Partial<CollaboratorPublic> = {},
): CollaboratorPublic {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    type: "management_company",
    brand_name: "УК Centrum",
    financial_group: "D",
    status: "ACTIVE",
    service_area: "Москва",
    working_hours: "24/7",
    website: null,
    rating: 4.5,
    ...override,
  };
}

function internalFixture(
  override: Partial<CollaboratorInternal> = {},
): CollaboratorInternal {
  return {
    ...publicFixture(),
    name: "ООО Centrum Management",
    legal_entity_type: "legal_entity",
    inn: null,
    ogrn: null,
    kpp: null,
    responsible_internal: null,
    contract_document_id: null,
    fallback_collaborator_id: null,
    contacts: [],
    financial_terms: {},
    api_integration: {},
    sla: {},
    counterparty_check: {},
    created_at: "2026-05-16T00:00:00Z",
    updated_at: "2026-05-16T00:00:00Z",
    ...override,
  };
}

describe("CollaboratorsTable", () => {
  it("показывает empty state когда data пуст", () => {
    render(<CollaboratorsTable data={[]} />);
    expect(screen.getByText(/не найдены/)).toBeInTheDocument();
  });

  it("рендерит юр.название для internal entries", () => {
    render(<CollaboratorsTable data={[internalFixture()]} />);
    expect(screen.getByText("ООО Centrum Management")).toBeInTheDocument();
    expect(screen.getByText("management_company")).toBeInTheDocument();
  });

  it("фоллбечит на brand_name для public entries (без name)", () => {
    render(<CollaboratorsTable data={[publicFixture()]} />);
    expect(screen.getByText("УК Centrum")).toBeInTheDocument();
  });

  it("рендерит человекочитаемые группы", () => {
    render(
      <CollaboratorsTable
        data={[
          internalFixture({ financial_group: "A" }),
          internalFixture({
            id: "22222222-2222-2222-2222-222222222222",
            financial_group: "D",
          }),
        ]}
      />,
    );
    expect(screen.getByText(/A — мы платим/)).toBeInTheDocument();
    expect(screen.getByText(/D — контакт/)).toBeInTheDocument();
  });

  it("рендерит status badge с color class", () => {
    const { container } = render(
      <CollaboratorsTable
        data={[
          internalFixture({ status: "ACTIVE" }),
          internalFixture({
            id: "22222222-2222-2222-2222-222222222222",
            status: "ARCHIVED",
          }),
        ]}
      />,
    );
    expect(container.querySelector(".bg-green-100")).toBeTruthy();
    expect(container.querySelector(".bg-red-100")).toBeTruthy();
  });

  it("link на detail page (URL-encoded id)", () => {
    render(
      <CollaboratorsTable
        data={[internalFixture({ id: "abc/with space" })]}
      />,
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute(
      "href",
      "/admin/collaborators/abc%2Fwith%20space",
    );
  });

  it("рейтинг показывает '—' если null", () => {
    render(
      <CollaboratorsTable
        data={[internalFixture({ rating: null })]}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("рейтинг отображается с одной decimal", () => {
    render(
      <CollaboratorsTable
        data={[internalFixture({ rating: 3.987 })]}
      />,
    );
    expect(screen.getByText("4.0")).toBeInTheDocument();
  });
});

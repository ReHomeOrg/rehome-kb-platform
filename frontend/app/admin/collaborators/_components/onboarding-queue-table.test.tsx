import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CollaboratorInternal } from "@/lib/api/types";

import OnboardingQueueTable from "./onboarding-queue-table";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

function fixture(
  override: Partial<CollaboratorInternal> = {},
): CollaboratorInternal {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    type: "management_company",
    brand_name: "УК Centrum",
    financial_group: "A",
    status: "PENDING_REVIEW",
    service_area: "Москва",
    working_hours: null,
    website: null,
    rating: null,
    name: "ООО Centrum",
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
    onboarding_source: "form",
    portal_access_level: "NONE",
    created_at: "2026-05-16T12:00:00Z",
    updated_at: "2026-05-16T12:00:00Z",
    ...override,
  };
}

describe("OnboardingQueueTable", () => {
  it("показывает empty state когда очередь пустая", () => {
    render(<OnboardingQueueTable data={[]} />);
    expect(screen.getByText(/Очередь пуста/)).toBeInTheDocument();
  });

  it("переводит onboarding_source в человекочитаемый label", () => {
    render(<OnboardingQueueTable data={[fixture()]} />);
    expect(screen.getByText("Публичная форма")).toBeInTheDocument();
  });

  it("staff_invite source → 'Staff-invited' label", () => {
    render(
      <OnboardingQueueTable
        data={[fixture({ onboarding_source: "staff_invite" })]}
      />,
    );
    expect(screen.getByText("Staff-invited")).toBeInTheDocument();
  });

  it("показывает name + type + группу в первой колонке", () => {
    render(<OnboardingQueueTable data={[fixture()]} />);
    expect(screen.getByText("ООО Centrum")).toBeInTheDocument();
    expect(
      screen.getByText(/management_company.*группа A/),
    ).toBeInTheDocument();
  });

  it("рендерит lifecycle-actions кнопку Активировать", () => {
    render(<OnboardingQueueTable data={[fixture()]} />);
    expect(
      screen.getByRole("button", { name: "Активировать" }),
    ).toBeInTheDocument();
  });

  it("link на detail page (URL-encoded id)", () => {
    render(<OnboardingQueueTable data={[fixture({ id: "abc/with space" })]} />);
    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveAttribute(
      "href",
      "/admin/collaborators/abc%2Fwith%20space",
    );
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AuditFilters from "./audit-filters";

const EMPTY_INITIAL = {
  actor_sub: "",
  resource_type: "",
  resource_id: "",
  action: "",
  q: "",
  since: "",
  until: "",
};

describe("AuditFilters", () => {
  it("renders form с role=search + aria-label", () => {
    render(<AuditFilters initial={EMPTY_INITIAL} />);
    expect(
      screen.getByRole("search", { name: "Audit log filters" }),
    ).toBeInTheDocument();
  });

  it("form submits GET на /admin/audit", () => {
    const { container } = render(<AuditFilters initial={EMPTY_INITIAL} />);
    const form = container.querySelector("form");
    expect(form?.method.toLowerCase()).toBe("get");
    expect(form?.getAttribute("action")).toBe("/admin/audit");
  });

  it("все input/select имеют aria-label (WCAG 1.3.1)", () => {
    render(<AuditFilters initial={EMPTY_INITIAL} />);
    expect(
      screen.getByLabelText("Actor subject identifier"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by resource type")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Filter by resource identifier"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by action name")).toBeInTheDocument();
    expect(screen.getByLabelText("Search metadata substring")).toBeInTheDocument();
    expect(
      screen.getByLabelText("From datetime (inclusive)"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Until datetime (exclusive)")).toBeInTheDocument();
  });

  it("preserves initial actor_sub как defaultValue", () => {
    render(
      <AuditFilters initial={{ ...EMPTY_INITIAL, actor_sub: "user-42" }} />,
    );
    const input = screen.getByLabelText(
      "Actor subject identifier",
    ) as HTMLInputElement;
    expect(input.defaultValue).toBe("user-42");
  });

  it("preserves initial q (metadata search)", () => {
    render(
      <AuditFilters initial={{ ...EMPTY_INITIAL, q: "article-foo" }} />,
    );
    const input = screen.getByLabelText(
      "Search metadata substring",
    ) as HTMLInputElement;
    expect(input.defaultValue).toBe("article-foo");
  });

  it("preserves initial since/until ISO values", () => {
    render(
      <AuditFilters
        initial={{
          ...EMPTY_INITIAL,
          since: "2026-01-01T00:00",
          until: "2026-12-31T23:59",
        }}
      />,
    );
    expect(
      (screen.getByLabelText("From datetime (inclusive)") as HTMLInputElement)
        .defaultValue,
    ).toBe("2026-01-01T00:00");
    expect(
      (screen.getByLabelText("Until datetime (exclusive)") as HTMLInputElement)
        .defaultValue,
    ).toBe("2026-12-31T23:59");
  });

  it("resource_type select содержит все expected options", () => {
    render(<AuditFilters initial={EMPTY_INITIAL} />);
    const select = screen.getByLabelText(
      "Filter by resource type",
    ) as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toContain("article");
    expect(values).toContain("article_question");  // Q&A module 2026-05-28
    expect(values).toContain("vault_secret");
    expect(values).toContain("webhook");
    // Default option «все» — empty value
    expect(values).toContain("");
  });

  it("resource_type select полностью sync'нут с backend RESOURCE_*", () => {
    /**
     * Контрактная сцепка с `backend/src/api/audit/actions.py::RESOURCE_*`.
     * Backend test `test_audit_resource_sync.py` проверяет sync c этой
     * стороны (parsing select markup); этот frontend test проверяет
     * что hardcoded set матчит документированный backend список.
     *
     * При добавлении RESOURCE_X в backend — обновить и этот expected_set,
     * и select markup. Reviewer 2026-05-28 §G2.
     */
    render(<AuditFilters initial={EMPTY_INITIAL} />);
    const select = screen.getByLabelText(
      "Filter by resource type",
    ) as HTMLSelectElement;
    const values = new Set(
      Array.from(select.options)
        .map((o) => o.value)
        .filter((v) => v !== ""),  // sentinel «все»
    );
    const expected = new Set([
      "admin_cache",
      "admin_category",
      "admin_system_config",
      "admin_task",
      "article",
      "article_question",
      "chat_session",
      "chat_unanswered",
      "collaborator",
      "document",
      "hr_employee",
      "premises_card",
      "vault_group",
      "vault_secret",
      "vault_user",
      "webhook",
    ]);
    expect(values).toEqual(expected);
  });

  it("q input имеет maxLength=200 (anti-DoS guard)", () => {
    render(<AuditFilters initial={EMPTY_INITIAL} />);
    const input = screen.getByLabelText(
      "Search metadata substring",
    ) as HTMLInputElement;
    expect(input.maxLength).toBe(200);
  });

  it("Reset link aria-label + href=/admin/audit", () => {
    render(<AuditFilters initial={EMPTY_INITIAL} />);
    const link = screen.getByRole("link", { name: "Reset all filters" });
    expect(link).toHaveAttribute("href", "/admin/audit");
  });

  it("Submit button renders «Применить»", () => {
    render(<AuditFilters initial={EMPTY_INITIAL} />);
    expect(
      screen.getByRole("button", { name: "Применить" }),
    ).toBeInTheDocument();
  });
});

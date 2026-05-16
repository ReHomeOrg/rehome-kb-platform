import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CollaboratorsFilters from "./collaborators-filters";

describe("CollaboratorsFilters", () => {
  it("renders все 14 type options + 'все'", () => {
    render(<CollaboratorsFilters initial={{}} />);
    const select = screen.getByLabelText(/Filter by collaborator type/);
    const options = select.querySelectorAll("option");
    // 14 types + 1 "все" placeholder = 15
    expect(options.length).toBe(15);
  });

  it("renders 5 statuses + 'все'", () => {
    render(<CollaboratorsFilters initial={{}} />);
    const select = screen.getByLabelText(/Filter by status/);
    expect(select.querySelectorAll("option").length).toBe(6);
  });

  it("preserves initial filter values via defaultValue", () => {
    render(
      <CollaboratorsFilters
        initial={{ type: "cleaning", status: "ACTIVE", service_area: "СПб" }}
      />,
    );
    const typeSelect = screen.getByLabelText(
      /Filter by collaborator type/,
    ) as HTMLSelectElement;
    const statusSelect = screen.getByLabelText(
      /Filter by status/,
    ) as HTMLSelectElement;
    const areaInput = screen.getByLabelText(
      /Filter by service area/,
    ) as HTMLInputElement;
    expect(typeSelect.value).toBe("cleaning");
    expect(statusSelect.value).toBe("ACTIVE");
    expect(areaInput.defaultValue).toBe("СПб");
  });

  it("form submits как GET на /admin/collaborators", () => {
    const { container } = render(<CollaboratorsFilters initial={{}} />);
    const form = container.querySelector("form");
    expect(form?.method.toLowerCase()).toBe("get");
    expect(form?.getAttribute("action")).toBe("/admin/collaborators");
  });
});

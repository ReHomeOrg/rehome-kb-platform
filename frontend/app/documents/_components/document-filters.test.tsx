import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DocumentFilters from "./document-filters";

const pushMock = vi.fn();
const searchParamsMock = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParamsMock,
}));

describe("DocumentFilters", () => {
  it("renders categories + statuses dropdowns", () => {
    render(
      <DocumentFilters
        initial={{ category: "", status: "", related_entity: "" }}
      />,
    );
    expect(screen.getByText(/публичные документы пользователей/)).toBeInTheDocument();
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
  });

  it("submits with category + status + related_entity", () => {
    pushMock.mockReset();
    render(
      <DocumentFilters
        initial={{ category: "B", status: "ACTIVE", related_entity: "user:abc" }}
      />,
    );
    fireEvent.click(screen.getByText("Применить"));
    const arg = pushMock.mock.calls[0][0];
    expect(arg).toContain("category=B");
    expect(arg).toContain("status=ACTIVE");
    expect(arg).toContain("related_entity=user");
  });

  it("submits without filters → bare /documents", () => {
    pushMock.mockReset();
    render(
      <DocumentFilters
        initial={{ category: "", status: "", related_entity: "" }}
      />,
    );
    fireEvent.click(screen.getByText("Применить"));
    expect(pushMock).toHaveBeenCalledWith("/documents");
  });
});

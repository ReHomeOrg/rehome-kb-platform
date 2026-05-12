import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ArticleFilters from "./article-filters";

const pushMock = vi.fn();
const searchParamsMock = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParamsMock,
}));

describe("ArticleFilters", () => {
  it("renders with initial values", () => {
    render(
      <ArticleFilters
        initial={{
          category: "rental",
          audience: "tenant",
          language: "ru",
          tags: "договор",
        }}
      />,
    );
    expect((screen.getByDisplayValue("rental") as HTMLInputElement).value).toBe(
      "rental",
    );
    expect(screen.getByDisplayValue("tenant")).toBeInTheDocument();
  });

  it("submits to /articles with URL params", () => {
    pushMock.mockReset();
    render(
      <ArticleFilters
        initial={{ category: "x", audience: "", language: "", tags: "" }}
      />,
    );
    const submit = screen.getByText("Применить");
    fireEvent.click(submit);
    expect(pushMock).toHaveBeenCalled();
    const arg = pushMock.mock.calls[0][0];
    expect(arg).toContain("/articles");
    expect(arg).toContain("category=x");
  });

  it("submits without params if all empty → bare /articles", () => {
    pushMock.mockReset();
    render(
      <ArticleFilters
        initial={{ category: "", audience: "", language: "", tags: "" }}
      />,
    );
    fireEvent.click(screen.getByText("Применить"));
    expect(pushMock).toHaveBeenCalledWith("/articles");
  });
});

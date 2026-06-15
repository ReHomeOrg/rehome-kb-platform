import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ArticleFilters from "./article-filters";

const pushMock = vi.fn();
const searchParamsMock = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParamsMock,
}));

const CATS = ["rental", "Глоссарий", "Платежи и финансы"];

describe("ArticleFilters", () => {
  it("renders with initial values (staff видит аудиторию/язык)", () => {
    render(
      <ArticleFilters
        initial={{
          category: "rental",
          audience: "tenant",
          language: "ru",
          tags: "договор",
        }}
        categories={CATS}
        isStaffAdmin={true}
      />,
    );
    expect((screen.getByDisplayValue("rental") as HTMLSelectElement).value).toBe(
      "rental",
    );
    expect(screen.getByDisplayValue("tenant")).toBeInTheDocument();
  });

  it("категория — выпадающий список со всеми категориями", () => {
    render(
      <ArticleFilters
        initial={{ category: "", audience: "", language: "", tags: "" }}
        categories={CATS}
        isStaffAdmin={false}
      />,
    );
    // option «Все категории» + по одной на каждую категорию
    expect(screen.getByRole("option", { name: "Все категории" })).toBeInTheDocument();
    for (const cat of CATS) {
      expect(screen.getByRole("option", { name: cat })).toBeInTheDocument();
    }
  });

  it("скрывает фильтры аудитории и языка для обычного пользователя", () => {
    render(
      <ArticleFilters
        initial={{ category: "", audience: "", language: "", tags: "" }}
        categories={CATS}
        isStaffAdmin={false}
      />,
    );
    expect(screen.queryByText("Аудитория")).not.toBeInTheDocument();
    expect(screen.queryByText("Язык")).not.toBeInTheDocument();
    // категория и теги остаются
    expect(screen.getByText("Категория")).toBeInTheDocument();
    expect(screen.getByText(/Теги/)).toBeInTheDocument();
  });

  it("submits to /articles with URL params", () => {
    pushMock.mockReset();
    render(
      <ArticleFilters
        initial={{ category: "rental", audience: "", language: "", tags: "" }}
        categories={CATS}
        isStaffAdmin={false}
      />,
    );
    fireEvent.click(screen.getByText("Применить"));
    expect(pushMock).toHaveBeenCalled();
    const arg = pushMock.mock.calls[0][0];
    expect(arg).toContain("/articles");
    expect(arg).toContain("category=rental");
  });

  it("submits without params if all empty → bare /articles", () => {
    pushMock.mockReset();
    render(
      <ArticleFilters
        initial={{ category: "", audience: "", language: "", tags: "" }}
        categories={CATS}
        isStaffAdmin={false}
      />,
    );
    fireEvent.click(screen.getByText("Применить"));
    expect(pushMock).toHaveBeenCalledWith("/articles");
  });
});

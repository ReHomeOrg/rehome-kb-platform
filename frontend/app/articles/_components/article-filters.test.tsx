import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ArticleFilters from "./article-filters";

const pushMock = vi.fn();
const searchParamsMock = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParamsMock,
}));

// slug ≠ title намеренно — чтобы тест ловил отправку именно slug, а не title.
const CATS = [
  { slug: "glossary", title: "Глоссарий" },
  { slug: "payments", title: "Платежи и финансы" },
  { slug: "rental", title: "Аренда жилья" },
];

describe("ArticleFilters", () => {
  it("renders with initial values (staff видит аудиторию/язык)", () => {
    render(
      <ArticleFilters
        initial={{
          category: "glossary",
          audience: "tenant",
          language: "ru",
          tags: "договор",
        }}
        categories={CATS}
        isStaffAdmin={true}
      />,
    );
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe(
      "glossary",
    );
    expect(screen.getByDisplayValue("tenant")).toBeInTheDocument();
  });

  it("категория — выпадающий список: value=slug, подпись=title", () => {
    render(
      <ArticleFilters
        initial={{ category: "", audience: "", language: "", tags: "" }}
        categories={CATS}
        isStaffAdmin={false}
      />,
    );
    expect(
      screen.getByRole("option", { name: "Все категории" }),
    ).toBeInTheDocument();
    const glossary = screen.getByRole("option", {
      name: "Глоссарий",
    }) as HTMLOptionElement;
    expect(glossary.value).toBe("glossary");
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
    expect(screen.getByText("Категория")).toBeInTheDocument();
    expect(screen.getByText(/Теги/)).toBeInTheDocument();
  });

  it("submits slug (не title) в URL", () => {
    pushMock.mockReset();
    render(
      <ArticleFilters
        initial={{ category: "glossary", audience: "", language: "", tags: "" }}
        categories={CATS}
        isStaffAdmin={false}
      />,
    );
    fireEvent.click(screen.getByText("Применить"));
    expect(pushMock).toHaveBeenCalled();
    const arg = pushMock.mock.calls[0][0];
    expect(arg).toContain("/articles");
    expect(arg).toContain("category=glossary");
    expect(arg).not.toContain("Глоссарий");
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

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ArticleSummary, Category } from "@/lib/api/types";

function article(
  id: string,
  title: string,
  category: string,
  audience = "tenant",
): ArticleSummary {
  return {
    id,
    slug: title.toLowerCase().replace(/\s+/g, "-"),
    title,
    category,
    audience,
    access_level: "PUBLIC",
    tags: [],
    status: "PUBLISHED",
    updated_at: "2026-05-12T00:00:00Z",
  };
}

function category(slug: string, title: string): Category {
  return { slug, title, description: null, article_count: 0, children: [] };
}

import ArticleCategoryList from "./article-category-list";

const CATEGORIES: Category[] = [
  category("rental", "Аренда"),
  category("payments", "Оплата"),
];

describe("ArticleCategoryList", () => {
  it("renders empty state when no articles", () => {
    render(
      <ArticleCategoryList
        articles={[]}
        categories={CATEGORIES}
        isStaffAdmin={false}
      />,
    );
    expect(screen.getByText(/Ничего не найдено/)).toBeInTheDocument();
  });

  it("groups articles under category headings in tree order", () => {
    render(
      <ArticleCategoryList
        articles={[
          article("1", "Как платить", "payments"),
          article("2", "Договор найма", "rental"),
          article("3", "Залог", "rental"),
        ]}
        categories={CATEGORIES}
        isStaffAdmin={false}
      />,
    );
    const headings = screen.getAllByRole("heading", { level: 2 });
    // Порядок групп — как в дереве категорий: Аренда раньше Оплаты.
    expect(headings[0]).toHaveTextContent("Аренда");
    expect(headings[1]).toHaveTextContent("Оплата");
  });

  it("numbers articles within a category, sorted by title", () => {
    render(
      <ArticleCategoryList
        articles={[
          article("3", "Залог", "rental"),
          article("2", "Договор найма", "rental"),
        ]}
        categories={CATEGORIES}
        isStaffAdmin={false}
      />,
    );
    const list = screen.getByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(list.tagName).toBe("OL");
    // Сортировка по алфавиту: «Договор найма» перед «Залог».
    expect(items[0]).toHaveTextContent("Договор найма");
    expect(items[1]).toHaveTextContent("Залог");
  });

  it("puts unknown-category articles into «Без категории»", () => {
    render(
      <ArticleCategoryList
        articles={[article("9", "Сирота", "unknown-cat")]}
        categories={CATEGORIES}
        isStaffAdmin={false}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: /Без категории/ }),
    ).toBeInTheDocument();
  });

  it("shows audience only for staff admin", () => {
    const { rerender } = render(
      <ArticleCategoryList
        articles={[article("1", "Договор найма", "rental", "tenant")]}
        categories={CATEGORIES}
        isStaffAdmin={false}
      />,
    );
    expect(screen.queryByText(/tenant/)).not.toBeInTheDocument();

    rerender(
      <ArticleCategoryList
        articles={[article("1", "Договор найма", "rental", "tenant")]}
        categories={CATEGORIES}
        isStaffAdmin
      />,
    );
    expect(screen.getByText(/tenant/)).toBeInTheDocument();
  });
});

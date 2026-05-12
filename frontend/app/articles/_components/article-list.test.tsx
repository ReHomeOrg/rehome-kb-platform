import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ArticleSummary, PaginationInfo } from "@/lib/api/types";

import ArticleList from "./article-list";

const sample: ArticleSummary = {
  id: "11111111-1111-1111-1111-111111111111",
  slug: "test-article",
  title: "Тестовая статья",
  category: "rental",
  audience: "tenant",
  access_level: "PUBLIC",
  tags: ["договор", "аренда"],
  status: "PUBLISHED",
  updated_at: "2026-05-12T00:00:00Z",
};

const NO_MORE: PaginationInfo = { cursor_next: null, has_more: false };
const HAS_MORE: PaginationInfo = { cursor_next: "abc123", has_more: true };

describe("ArticleList", () => {
  it("renders empty state when no data", () => {
    render(
      <ArticleList data={[]} pagination={NO_MORE} currentParamsString="" />,
    );
    expect(screen.getByText(/Ничего не найдено/)).toBeInTheDocument();
  });

  it("renders article cards", () => {
    render(
      <ArticleList
        data={[sample]}
        pagination={NO_MORE}
        currentParamsString=""
      />,
    );
    expect(screen.getByText("Тестовая статья")).toBeInTheDocument();
    expect(screen.getByText(/rental/)).toBeInTheDocument();
    expect(screen.getByText("договор")).toBeInTheDocument();
  });

  it("renders next page link when has_more", () => {
    render(
      <ArticleList
        data={[sample]}
        pagination={HAS_MORE}
        currentParamsString="category=rental"
      />,
    );
    const nextLink = screen.getByText(/Следующая страница/);
    expect(nextLink).toBeInTheDocument();
    expect(nextLink.closest("a")?.getAttribute("href")).toContain(
      "cursor=abc123",
    );
  });

  it("omits next page link when no more", () => {
    render(
      <ArticleList
        data={[sample]}
        pagination={NO_MORE}
        currentParamsString=""
      />,
    );
    expect(screen.queryByText(/Следующая страница/)).not.toBeInTheDocument();
  });
});

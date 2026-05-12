import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Category } from "@/lib/api/types";

import CategoryTree from "./category-tree";

const leaf = (slug: string, count = 1): Category => ({
  slug,
  title: slug.toUpperCase(),
  description: null,
  article_count: count,
  children: [],
});

describe("CategoryTree", () => {
  it("renders empty state when no nodes", () => {
    render(<CategoryTree nodes={[]} />);
    expect(screen.getByText(/Категории пока не созданы/)).toBeInTheDocument();
  });

  it("renders single root", () => {
    render(<CategoryTree nodes={[leaf("root", 5)]} />);
    expect(screen.getByText("ROOT")).toBeInTheDocument();
    expect(screen.getByText("(5)")).toBeInTheDocument();
  });

  it("renders 2-level nesting", () => {
    const tree: Category[] = [
      {
        ...leaf("root", 10),
        children: [leaf("child-a"), leaf("child-b")],
      },
    ];
    render(<CategoryTree nodes={tree} />);
    expect(screen.getByText("ROOT")).toBeInTheDocument();
    expect(screen.getByText("CHILD-A")).toBeInTheDocument();
    expect(screen.getByText("CHILD-B")).toBeInTheDocument();
  });

  it("renders 3-level nesting (recursion test)", () => {
    const tree: Category[] = [
      {
        ...leaf("l0"),
        children: [
          {
            ...leaf("l1"),
            children: [leaf("l2")],
          },
        ],
      },
    ];
    render(<CategoryTree nodes={tree} />);
    expect(screen.getByText("L0")).toBeInTheDocument();
    expect(screen.getByText("L1")).toBeInTheDocument();
    expect(screen.getByText("L2")).toBeInTheDocument();
  });

  it("links to /articles?category=<slug>", () => {
    render(<CategoryTree nodes={[leaf("rental")]} />);
    const link = screen.getByText("RENTAL").closest("a");
    expect(link?.getAttribute("href")).toBe("/articles?category=rental");
  });

  it("URL-encodes Cyrillic slug", () => {
    render(<CategoryTree nodes={[leaf("аренда")]} />);
    const link = screen.getByText("АРЕНДА").closest("a");
    expect(link?.getAttribute("href")).toBe(
      "/articles?category=" + encodeURIComponent("аренда"),
    );
  });

  it("shows zero-count categories (UX для навигации)", () => {
    render(<CategoryTree nodes={[leaf("empty", 0)]} />);
    expect(screen.getByText("EMPTY")).toBeInTheDocument();
    expect(screen.getByText("(0)")).toBeInTheDocument();
  });
});

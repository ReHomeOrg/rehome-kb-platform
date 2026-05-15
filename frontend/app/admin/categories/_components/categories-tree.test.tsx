import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Category } from "@/lib/api/types";

import CategoriesTree from "./categories-tree";

function _node(over: Partial<Category> = {}): Category {
  return {
    slug: "wiki",
    title: "Wiki",
    description: null,
    article_count: 42,
    children: [],
    ...over,
  };
}

describe("CategoriesTree", () => {
  it("renders error state с role=status", () => {
    render(<CategoriesTree data={[]} error="Требуется авторизация." />);
    expect(screen.getByRole("status")).toHaveTextContent("авторизация");
  });

  it("renders empty state когда нет категорий", () => {
    render(<CategoriesTree data={[]} error={null} />);
    expect(screen.getByText(/нет/i)).toBeInTheDocument();
  });

  it("renders root tree с role=tree + aria-label", () => {
    render(<CategoriesTree data={[_node()]} error={null} />);
    expect(
      screen.getByRole("tree", { name: "Category tree" }),
    ).toBeInTheDocument();
  });

  it("renders title + slug + count для корневой ноды", () => {
    render(
      <CategoriesTree
        data={[_node({ slug: "договоры", article_count: 7 })]}
        error={null}
      />,
    );
    expect(screen.getByText("Wiki")).toBeInTheDocument();
    expect(screen.getByText("договоры")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("renders description под node когда есть", () => {
    render(
      <CategoriesTree
        data={[_node({ description: "Корневой узел" })]}
        error={null}
      />,
    );
    expect(screen.getByText("Корневой узел")).toBeInTheDocument();
  });

  it("recursive — child nodes рендерятся под parent (role=group)", () => {
    const tree: Category = _node({
      slug: "parent",
      title: "Parent",
      children: [
        _node({ slug: "child-1", title: "Child 1" }),
        _node({ slug: "child-2", title: "Child 2" }),
      ],
    });
    render(<CategoriesTree data={[tree]} error={null} />);
    const groups = screen.getAllByRole("group");
    // single group containing 2 children
    expect(groups).toHaveLength(1);
    expect(within(groups[0]).getByText("Child 1")).toBeInTheDocument();
    expect(within(groups[0]).getByText("Child 2")).toBeInTheDocument();
  });

  it("error takes precedence над empty + tree", () => {
    render(<CategoriesTree data={[_node()]} error="Ошибка 500" />);
    expect(screen.getByText("Ошибка 500")).toBeInTheDocument();
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Tag } from "@/lib/api/types";

import TagsList from "./tags-list";

function _tag(over: Partial<Tag> = {}): Tag {
  return {
    name: "налог",
    article_count: 5,
    ...over,
  };
}

describe("TagsList", () => {
  it("renders error state с role=status", () => {
    render(<TagsList data={[]} error="Требуется авторизация." />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("авторизация");
  });

  it("renders empty state когда нет тегов", () => {
    render(<TagsList data={[]} error={null} />);
    expect(screen.getByText(/не найдено/i)).toBeInTheDocument();
  });

  it("renders tag rows", () => {
    render(
      <TagsList
        data={[_tag(), _tag({ name: "договор", article_count: 12 })]}
        error={null}
      />,
    );
    expect(screen.getByText("налог")).toBeInTheDocument();
    expect(screen.getByText("договор")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("renders table с aria-label", () => {
    render(<TagsList data={[_tag()]} error={null} />);
    expect(screen.getByRole("table", { name: "Tags list" })).toBeInTheDocument();
  });

  it("error takes precedence над пустыми данными", () => {
    render(<TagsList data={[]} error="Ошибка 500" />);
    expect(screen.getByText("Ошибка 500")).toBeInTheDocument();
    expect(screen.queryByText(/не найдено/i)).not.toBeInTheDocument();
  });
});

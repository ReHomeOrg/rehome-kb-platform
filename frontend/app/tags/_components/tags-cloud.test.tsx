import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Tag } from "@/lib/api/types";

import TagsCloud from "./tags-cloud";

const tag = (name: string, count: number): Tag => ({ name, article_count: count });

describe("TagsCloud", () => {
  it("renders empty state", () => {
    render(<TagsCloud tags={[]} />);
    expect(screen.getByText(/Тегов пока нет/)).toBeInTheDocument();
  });

  it("renders tags with article_count", () => {
    render(<TagsCloud tags={[tag("договор", 5), tag("аренда", 3)]} />);
    expect(screen.getByText("договор")).toBeInTheDocument();
    expect(screen.getByText("(5)")).toBeInTheDocument();
    expect(screen.getByText("аренда")).toBeInTheDocument();
  });

  it("links to /articles?tags=<name>", () => {
    render(<TagsCloud tags={[tag("rental", 2)]} />);
    const link = screen.getByText("rental").closest("a");
    expect(link?.getAttribute("href")).toBe("/articles?tags=rental");
  });

  it("encodes Cyrillic tag name in href", () => {
    render(<TagsCloud tags={[tag("договор", 5)]} />);
    const link = screen.getByText("договор").closest("a");
    expect(link?.getAttribute("href")).toBe(
      "/articles?tags=" + encodeURIComponent("договор"),
    );
  });

  it("applies larger size class к top tag (highest count)", () => {
    render(
      <TagsCloud
        tags={[
          tag("top", 100),
          tag("low", 5),
        ]}
      />,
    );
    const topLink = screen.getByText("top").closest("a");
    const lowLink = screen.getByText("low").closest("a");
    expect(topLink?.className).toContain("text-lg");
    // 5/100 = 5% — bottom quartile
    expect(lowLink?.className).toContain("text-xs");
  });

  it("handles maxCount=0 (all zero) без NaN", () => {
    render(<TagsCloud tags={[tag("a", 0), tag("b", 0)]} />);
    const aLink = screen.getByText("a").closest("a");
    // ratio 0/0 → guard вернёт smallest
    expect(aLink?.className).toContain("text-xs");
  });
});

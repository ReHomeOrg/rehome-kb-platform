import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Citation } from "@/lib/api/types";

import CitationsBlock from "./citations-block";

function makeCitation(over: Partial<Citation> = {}): Citation {
  return {
    type: "article",
    id: "id-1",
    title: "Договор аренды",
    slug: "rent-contract",
    chunk_index: 0,
    score: 0.025,
    url: "/articles/rent-contract",
    ...over,
  };
}

describe("CitationsBlock", () => {
  it("returns null when no citations", () => {
    const { container } = render(<CitationsBlock citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders title with link to /articles/{slug}", () => {
    render(<CitationsBlock citations={[makeCitation()]} />);
    const link = screen.getByRole("link", { name: /Договор аренды/i });
    expect(link.getAttribute("href")).toBe("/articles/rent-contract");
  });

  it("shows chunk index as 1-indexed badge", () => {
    render(
      <CitationsBlock citations={[makeCitation({ chunk_index: 4 })]} />,
    );
    // 4 (0-indexed) → display "chunk #5"
    expect(screen.getByText(/chunk #5/i)).toBeInTheDocument();
  });

  it("renders count of citations in summary", () => {
    render(
      <CitationsBlock
        citations={[
          makeCitation({ id: "1", title: "One", slug: "one" }),
          makeCitation({ id: "2", title: "Two", slug: "two" }),
          makeCitation({ id: "3", title: "Three", slug: "three" }),
        ]}
      />,
    );
    expect(screen.getByText(/Источники \(3\)/i)).toBeInTheDocument();
  });

  it("renders all citations as list items", () => {
    render(
      <CitationsBlock
        citations={[
          makeCitation({ id: "1", title: "Aren", slug: "aren" }),
          makeCitation({ id: "2", title: "Bren", slug: "bren" }),
        ]}
      />,
    );
    expect(screen.getByText("Aren")).toBeInTheDocument();
    expect(screen.getByText("Bren")).toBeInTheDocument();
  });
});

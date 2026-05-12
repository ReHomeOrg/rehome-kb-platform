import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SearchHit } from "@/lib/api/types";

import SearchResults from "./search-results";

const hit: SearchHit = {
  type: "article",
  id: "abc",
  title: "Сервисный платёж",
  snippet: "Что такое <b>сервисный платёж</b>",
  score: 0.42,
};

describe("SearchResults", () => {
  it("empty state на zero hits", () => {
    render(<SearchResults hits={[]} />);
    expect(screen.getByText(/Ничего не найдено/)).toBeInTheDocument();
  });

  it("renders title + score", () => {
    render(<SearchResults hits={[hit]} />);
    expect(screen.getByText("Сервисный платёж")).toBeInTheDocument();
    expect(screen.getByText(/score 0\.420/)).toBeInTheDocument();
  });

  it("renders sanitized <b> snippet", () => {
    const { container } = render(<SearchResults hits={[hit]} />);
    const boldEl = container.querySelector("b");
    expect(boldEl?.textContent).toBe("сервисный платёж");
  });

  it("renders without snippet (null)", () => {
    const noSnippet: SearchHit = { ...hit, snippet: null };
    render(<SearchResults hits={[noSnippet]} />);
    expect(screen.getByText("Сервисный платёж")).toBeInTheDocument();
  });

  it("sanitizes <script> in snippet", () => {
    const malicious: SearchHit = {
      ...hit,
      snippet: "<script>alert(1)</script>",
    };
    render(<SearchResults hits={[malicious]} />);
    expect(document.querySelector("script")).toBeNull();
  });
});

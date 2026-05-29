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

  it("renders article_question citation with anchor link + Q&A label", () => {
    render(
      <CitationsBlock
        citations={[
          makeCitation({
            type: "article_question",
            question_id: "q-42",
            url: "/articles/rent-contract#question-q-42",
            chunk_index: 0,
          }),
        ]}
      />,
    );
    const link = screen.getByRole("link", { name: /Договор аренды/i });
    // Anchor для deep-link на конкретный Q&A блок.
    expect(link.getAttribute("href")).toBe(
      "/articles/rent-contract#question-q-42",
    );
    // Q&A variant label вместо "chunk #N".
    expect(screen.getByText(/ответ на вопрос пользователя/i)).toBeInTheDocument();
    expect(screen.queryByText(/chunk #/i)).not.toBeInTheDocument();
  });

  it("mixed citations render both article and Q&A variants", () => {
    render(
      <CitationsBlock
        citations={[
          makeCitation({ id: "1", title: "Body", slug: "body", chunk_index: 2 }),
          makeCitation({
            type: "article_question",
            id: "2",
            title: "Q answer",
            slug: "q",
            question_id: "qid",
            url: "/articles/q#question-qid",
          }),
        ]}
      />,
    );
    expect(screen.getByText(/chunk #3/i)).toBeInTheDocument();
    expect(screen.getByText(/ответ на вопрос пользователя/i)).toBeInTheDocument();
  });
});

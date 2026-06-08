import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ArticleMarkdown from "./article-markdown";

// NB: react-markdown 10 рендерит асинхронно (использует unified pipeline);
// нужно await findBy*. Для тестов без ожидаемого элемента — await
// микро-задачи.
async function flushMicrotasks(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("ArticleMarkdown", () => {
  it("renders headings", async () => {
    render(<ArticleMarkdown content="# Title" />);
    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Title");
  });

  it("renders links", async () => {
    render(<ArticleMarkdown content="[link](https://example.org)" />);
    const link = await screen.findByRole("link", { name: "link" });
    expect(link).toHaveAttribute("href", "https://example.org");
  });

  it("renders internal article links", async () => {
    render(<ArticleMarkdown content="[Перейти к статье 137](/articles/foo)" />);
    const link = await screen.findByRole("link", {
      name: "Перейти к статье 137",
    });
    expect(link).toHaveAttribute("href", "/articles/foo");
  });

  it("escapes raw HTML (no rehype-raw)", async () => {
    const { container } = render(
      <ArticleMarkdown content='<script>alert("xss")</script>' />,
    );
    await flushMicrotasks();
    // Raw HTML escape'нут — нет script-тега в DOM.
    expect(container.querySelector("script")).toBeNull();
  });

  it("renders GFM strikethrough", async () => {
    const { container } = render(
      <ArticleMarkdown content="~~struck~~ text" />,
    );
    await flushMicrotasks();
    expect(container.querySelector("del")?.textContent).toBe("struck");
  });
});

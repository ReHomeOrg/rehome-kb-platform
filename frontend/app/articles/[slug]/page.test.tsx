import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ArticleDetailPage from "./page";
import { getArticle } from "@/lib/api/articles";
import { getSessionAccess } from "@/lib/auth/access";

vi.mock("@/app/_components/nav", () => ({ default: () => <nav /> }));
vi.mock("../_components/article-markdown", () => ({
  default: () => <div data-testid="md" />,
}));
vi.mock("../_components/article-qa-section", () => ({
  default: () => <div data-testid="qa" />,
}));
vi.mock("../_components/delete-button", () => ({
  default: () => <button>Удалить</button>,
}));
vi.mock("@/lib/api/articles", () => ({ getArticle: vi.fn() }));
vi.mock("@/lib/auth/access", () => ({ getSessionAccess: vi.fn() }));

const article = {
  id: "1",
  slug: "test",
  title: "Заголовок",
  summary: null,
  body_markdown: "# x",
  category: "Глоссарий",
  audience: "tenant",
  language: "ru",
  tags: [],
  access_level: "PUBLIC",
  status: "PUBLISHED",
  published_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

afterEach(() => vi.clearAllMocks());

async function renderWith(isStaffAdmin: boolean): Promise<void> {
  vi.mocked(getArticle).mockResolvedValue(article);
  vi.mocked(getSessionAccess).mockResolvedValue({ isLoggedIn: true, isStaffAdmin });
  render(await ArticleDetailPage({ params: Promise.resolve({ slug: "test" }) }));
}

describe("ArticleDetailPage RBAC-видимость", () => {
  it("обычный пользователь: нет edit/delete, нет аудитории/языка", async () => {
    await renderWith(false);
    expect(screen.queryByText("Редактировать")).not.toBeInTheDocument();
    expect(screen.queryByText("Удалить")).not.toBeInTheDocument();
    expect(screen.queryByText("Аудитория")).not.toBeInTheDocument();
    expect(screen.queryByText("Язык")).not.toBeInTheDocument();
    expect(screen.getByText("Категория")).toBeInTheDocument();
  });

  it("staff_admin: видит edit/delete и аудиторию/язык", async () => {
    await renderWith(true);
    expect(screen.getByText("Редактировать")).toBeInTheDocument();
    expect(screen.getByText("Удалить")).toBeInTheDocument();
    expect(screen.getByText("Аудитория")).toBeInTheDocument();
    expect(screen.getByText("Язык")).toBeInTheDocument();
  });
});

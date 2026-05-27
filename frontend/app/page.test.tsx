import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock next/headers cookies() — server component dependency.
vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

// Mock listArticles — server-side fetch не должен реально hit'ить backend в тестах.
vi.mock("@/lib/api/articles", () => ({
  listArticles: vi.fn(),
}));

import { cookies } from "next/headers";

import { listArticles } from "@/lib/api/articles";

import Home from "./page";

interface FakeCookieStore {
  has(name: string): boolean;
}

function setCookies(store: FakeCookieStore): void {
  (cookies as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(store);
}

function mockFaq(items: { slug: string; title: string; tags: string[] }[]): void {
  (listArticles as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: items.map((it) => ({
      id: it.slug,
      slug: it.slug,
      title: it.title,
      category: "FAQ",
      audience: "all",
      access_level: "PUBLIC",
      tags: it.tags,
      status: "PUBLISHED",
      updated_at: "2026-05-27T00:00:00Z",
    })),
    pagination: { cursor_next: null, has_more: false },
  });
}

describe("Home (help.rehome.one landing)", () => {
  beforeEach(() => {
    setCookies({ has: () => false });
    mockFaq([]);
  });

  it("renders the help-center heading", async () => {
    const tree = await Home();
    render(tree);
    expect(
      screen.getByRole("heading", { name: /help\.rehome\.one/i }),
    ).toBeInTheDocument();
  });

  it("renders search form pointing к /articles", async () => {
    const tree = await Home();
    render(tree);
    const input = screen.getByPlaceholderText(/сервисный сбор/i);
    expect(input).toBeInTheDocument();
    expect(input.closest("form")).toHaveAttribute("action", "/articles");
    expect(input.closest("form")).toHaveAttribute("method", "get");
  });

  it("renders all 11 ПЗ categories with links", async () => {
    const tree = await Home();
    render(tree);
    expect(screen.getByText("Начало работы и регистрация")).toBeInTheDocument();
    expect(screen.getByText("Платежи и финансы")).toBeInTheDocument();
    expect(screen.getByText("Для собственников")).toBeInTheDocument();
    expect(screen.getByText("Безопасность, данные и поддержка")).toBeInTheDocument();
    // Все category card'ы — это ссылки на /articles?category=...
    const categoryLinks = screen.getAllByRole("link", { name: /Начало работы/i });
    expect(categoryLinks[0]).toHaveAttribute(
      "href",
      expect.stringContaining("/articles?category="),
    );
  });

  it("renders top FAQ when API returns items", async () => {
    mockFaq([
      { slug: "what-is-rehome", title: "Что такое reHome?", tags: ["платформа"] },
      { slug: "service-fee", title: "Что такое сервисный сбор?", tags: ["оплата"] },
    ]);
    const tree = await Home();
    render(tree);
    expect(screen.getByText("Что такое reHome?")).toBeInTheDocument();
    expect(screen.getByText("Что такое сервисный сбор?")).toBeInTheDocument();
    // FAQ section header
    expect(screen.getByText(/Популярные вопросы/i)).toBeInTheDocument();
  });

  it("hides FAQ section if API returns empty (degraded mode)", async () => {
    mockFaq([]);
    const tree = await Home();
    render(tree);
    expect(screen.queryByText(/Популярные вопросы/i)).not.toBeInTheDocument();
  });

  it("renders AI chat CTA pointing к /chat", async () => {
    const tree = await Home();
    render(tree);
    const ctaLink = screen.getByRole("link", { name: /Открыть чат/i });
    expect(ctaLink).toHaveAttribute("href", "/chat");
  });

  it("renders 'Войти' link when no kb_session cookie", async () => {
    setCookies({ has: () => false });
    const tree = await Home();
    render(tree);
    const link = screen.getByRole("link", { name: /Войти/i });
    expect(link).toHaveAttribute("href", "/login");
  });

  it("renders 'Выйти' button when kb_session present", async () => {
    setCookies({ has: (name: string) => name === "kb_session" });
    const tree = await Home();
    render(tree);
    expect(screen.getByRole("button", { name: /Выйти/i })).toBeInTheDocument();
  });

  it("degrades gracefully if listArticles throws", async () => {
    (listArticles as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("backend down"),
    );
    const tree = await Home();
    render(tree);
    // Landing всё равно рендерится — heading + категории.
    expect(
      screen.getByRole("heading", { name: /help\.rehome\.one/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Популярные вопросы/i)).not.toBeInTheDocument();
  });
});

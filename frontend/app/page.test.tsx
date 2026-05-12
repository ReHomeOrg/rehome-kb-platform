import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import Home from "./page";

// Mock next/headers cookies() — server component dependency.
vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

import { cookies } from "next/headers";

interface FakeCookieStore {
  has(name: string): boolean;
}

function setCookies(store: FakeCookieStore): void {
  (cookies as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(store);
}

describe("Home page", () => {
  beforeEach(() => {
    setCookies({ has: () => false });
  });

  it("renders the help-center heading", async () => {
    const tree = await Home();
    render(tree);
    expect(
      screen.getByRole("heading", { name: /help\.rehome\.one/i }),
    ).toBeInTheDocument();
  });

  it("renders the coming-soon notice referencing Phase 1 E3", async () => {
    const tree = await Home();
    render(tree);
    expect(screen.getByText(/Coming soon/i)).toBeInTheDocument();
    expect(screen.getByText(/Phase 1, E3/i)).toBeInTheDocument();
  });

  it("renders the description mentioning reHome knowledge base", async () => {
    const tree = await Home();
    render(tree);
    expect(screen.getByText(/База знаний reHome/i)).toBeInTheDocument();
  });

  it("renders 'Войти' link when no kb_session cookie", async () => {
    setCookies({ has: () => false });
    const tree = await Home();
    render(tree);
    const link = screen.getByRole("link", { name: /Войти/i });
    expect(link).toHaveAttribute("href", "/login");
  });

  it("renders 'Выйти' button (form post to logout) when kb_session present", async () => {
    setCookies({ has: (name: string) => name === "kb_session" });
    const tree = await Home();
    render(tree);
    expect(screen.getByRole("button", { name: /Выйти/i })).toBeInTheDocument();
  });
});

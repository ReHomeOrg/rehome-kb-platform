import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import LoginPage from "./page";

describe("LoginPage", () => {
  it("renders heading 'Вход в reHome KB'", () => {
    render(<LoginPage />);
    expect(
      screen.getByRole("heading", { name: /Вход в reHome KB/i }),
    ).toBeInTheDocument();
  });

  it("renders SSO button that links to /help/api/auth/login", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: /reHome SSO/i });
    expect(link).toHaveAttribute("href", "/help/api/auth/login");
  });
});

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

  it("renders SSO button that links to the basePath-aware login route", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: /reHome SSO/i });
    // В тестовой среде NEXT_PUBLIC_BASE_PATH="" (см. vitest.config) → без префикса.
    expect(link).toHaveAttribute("href", "/api/auth/login");
  });
});

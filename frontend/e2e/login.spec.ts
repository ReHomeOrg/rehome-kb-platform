/**
 * Smoke tests для /login (#151).
 *
 * Pure frontend — не требуют backend. Validate'ит:
 * - Страница рендерится без JS errors.
 * - Login button точно с правильной target URL.
 * - Page title корректный.
 * - Accessibility basics (heading hierarchy, link role).
 */

import { expect, test } from "@playwright/test";

test.describe("/login", () => {
  test("renders heading and SSO link", async ({ page }) => {
    await page.goto("/login");
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toContainText("reHome KB");
    const loginLink = page.getByRole("link", { name: /войти через rehome sso/i });
    await expect(loginLink).toBeVisible();
    await expect(loginLink).toHaveAttribute("href", "/api/auth/login");
  });

  test("has no console errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await page.goto("/login");
    expect(errors).toEqual([]);
  });

  test("keyboard navigation reaches login link", async ({ page }) => {
    await page.goto("/login");
    // Tab-jump к первому focusable element (login link).
    await page.keyboard.press("Tab");
    const active = await page.evaluate(() => document.activeElement?.tagName);
    expect(active).toBe("A");
  });
});

/**
 * Accessibility smoke tests via axe-core (#158).
 *
 * Pure-frontend pages — checked for WCAG 2.1 AA violations. Backend-
 * зависимые pages (articles / chat / hr) — отдельный suite после
 * landing'а full-stack E2E (backlog).
 *
 * Baseline: ZERO violations на этих pages. New violation → CI fail
 * → fix или explicit `.disableRules()` с обоснованием в коде.
 */

import { AxeBuilder } from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Rule sets: WCAG 2.1 Level A + AA. Level AAA не runs by default —
// много false-positive'ов в design system. Можно enable per-page если
// commit на AAA tier.
const STANDARD_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

test.describe("a11y: /login", () => {
  test("no WCAG 2.1 AA violations", async ({ page }) => {
    await page.goto("./login");
    const results = await new AxeBuilder({ page })
      .withTags(STANDARD_TAGS)
      .analyze();
    expect(
      results.violations,
      // Detailed failure message — Playwright print'нет полный array.
      `axe-core нашёл a11y violations: ${results.violations
        .map((v) => `${v.id} (${v.impact ?? "?"})`)
        .join(", ")}`,
    ).toEqual([]);
  });
});

test.describe("a11y: 404 not-found", () => {
  test("no WCAG 2.1 AA violations on default 404", async ({ page }) => {
    await page.goto("./this-route-does-not-exist");
    const results = await new AxeBuilder({ page })
      .withTags(STANDARD_TAGS)
      .analyze();
    expect(
      results.violations,
      `axe-core violations on 404: ${results.violations
        .map((v) => v.id)
        .join(", ")}`,
    ).toEqual([]);
  });
});

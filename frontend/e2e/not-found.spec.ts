/**
 * Smoke tests для 404 / not-found rendering (#151).
 *
 * Pure frontend — Next.js рендерит default 404 page для несуществующих
 * routes. Validate'ит что error boundary не падает.
 */

import { expect, test } from "@playwright/test";

test.describe("404 not-found", () => {
  test("unknown route renders 404 page", async ({ page }) => {
    const response = await page.goto("/this-route-does-not-exist");
    expect(response?.status()).toBe(404);
  });
});

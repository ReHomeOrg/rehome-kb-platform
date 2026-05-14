/**
 * Playwright config для E2E smoke tests (#151).
 *
 * Smoke tests запускаются против локального dev server (`npm run dev`)
 * — не требуют backend running. Backend-зависимые сценарии (chat,
 * articles auth) — отдельный smoke suite в follow-up, требует docker
 * compose stack.
 *
 * Локальный запуск:
 *   cd frontend
 *   npx playwright install chromium     # one-time, скачивает браузер
 *   npm run e2e
 *
 * CI integration — follow-up PR (требует Playwright Docker action +
 * ~250MB browser cache в CI environment).
 */

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // Параллелизация — но один worker для надёжности smoke tests
  // (avoid flaky-by-race на single dev server).
  fullyParallel: false,
  workers: 1,
  // CI: 2 retries на flaky; local: 0 — failures должны быть видны
  // immediately.
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  // Базовый URL — Next dev server. Override через PLAYWRIGHT_BASE_URL.
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    // Trace на retry — debugging help'er.
    trace: "on-first-retry",
    // Default timeout per action — 10s достаточно для local;
    // sandboxed CI может быть медленнее, но retries compensate.
    actionTimeout: 10_000,
  },
  // Стандартный Chromium — coverage для основных user flows. Mobile /
  // WebKit — после base smoke pass'а.
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Web server auto-spawn — Playwright стартует Next dev server до
  // тестов и kills'нет после. `reuseExistingServer` пропускает
  // spawn если localhost:3000 уже занят (для local iteration).
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});

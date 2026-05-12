import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["app/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
      exclude: [
        "**/*.test.{ts,tsx}",
        "**/*.d.ts",
        // Route handlers зависят от Next.js runtime (cookies(), NextRequest);
        // тестируются ниже через mocking, но порог 60% для них требует
        // полноценного integration setup — defer на E1.3.4.
        "app/api/auth/**",
        // Page shells (`app/**/page.tsx`) — тонкая обёртка над компонентами
        // которые уже тестируются индивидуально. Unit-тестировать
        // requires SSR mocking всего пайплайна (cookies, fetch, etc.) —
        // E2E (Playwright) покроет в UI.6 polish sub-PR.
        "app/**/page.tsx",
        "app/**/not-found.tsx",
        "app/**/layout.tsx",
        // Message thread — complex SSE consume + useEffect. Unit-тестировать
        // сложно (mock'ать AsyncIterableIterator + fetch + router); E2E
        // покроет реальный flow. Logic-методы streamMessage/getSession
        // покрыты в lib/api/chat.test.ts.
        "app/chat/_components/message-thread.tsx",
      ],
      thresholds: {
        lines: 60,
        functions: 60,
        branches: 60,
        statements: 60,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});

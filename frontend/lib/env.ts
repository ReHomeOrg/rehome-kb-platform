/**
 * Environment variable validation для frontend (UI.1 #75).
 *
 * Используется только server-side (Server Components, API route handlers).
 * Client-side process.env работает только для NEXT_PUBLIC_* префикса.
 */

/**
 * Backend API base URL — server-side (Next.js → backend) calls.
 * Default — localhost для dev. Production переопределяет через env.
 *
 * Normalize: убираем trailing slash, чтобы `${BACKEND_BASE_URL}/api/v1/...`
 * не давало двойной слэш.
 */
export function getBackendBaseUrl(): string {
  const raw = process.env.BACKEND_BASE_URL ?? "http://localhost:8000";
  // Validate URL parse to catch typos early.
  try {
    new URL(raw);
  } catch {
    throw new Error(
      `BACKEND_BASE_URL не является валидным URL: ${raw}`,
    );
  }
  return raw.replace(/\/+$/, "");
}

/**
 * Универсальный typed API client для frontend (UI.1 #75).
 *
 * Двойной режим работы:
 * - **SSR / Server Components** (`typeof window === 'undefined'`):
 *   absolute URL `BACKEND_BASE_URL + path`, Authorization Bearer из
 *   `kb_session` cookie через `next/headers.cookies()`.
 * - **Browser / Client Components**: relative URL `/api/kb<path>`,
 *   browser автоматически шлёт cookie, Next.js proxy route добавляет
 *   Authorization header.
 *
 * Для SSE — отдельный path `/api/kb-sse<path>` (см. chat.ts).
 */

import { COOKIE_SESSION } from "@/lib/auth/cookies";
import { getBackendBaseUrl } from "@/lib/env";
import { BASE_PATH } from "@/lib/base-path";

/**
 * HTTP error от API. Содержит status code + parsed body (если был JSON).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `API error ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/**
 * Detect SSR runtime via `typeof window === 'undefined'`.
 *
 * **Функция, не const**, чтобы test environment мог переключаться
 * между browser (jsdom — window defined) и SSR (node — window undefined).
 */
function isServer(): boolean {
  return typeof window === "undefined";
}

async function buildHeaders(extraHeaders?: HeadersInit): Promise<Headers> {
  const headers = new Headers(extraHeaders);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (isServer()) {
    // Server-side: читаем cookie через next/headers
    const { cookies } = await import("next/headers");
    const cookieStore = await cookies();
    const session = cookieStore.get(COOKIE_SESSION)?.value;
    if (session) {
      headers.set("Authorization", `Bearer ${session}`);
    }
  }
  // Browser: ничего не делаем — proxy route аттачит Bearer.
  return headers;
}

function buildUrl(path: string): string {
  if (isServer()) {
    return `${getBackendBaseUrl()}${path}`;
  }
  // Browser → через proxy `/api/kb<path>` (path начинается с `/api/v1/...`)
  const prefix = BASE_PATH;
  return `${prefix}/api/kb${path}`;
}

/**
 * Универсальный fetch-helper.
 *
 * `path` должен начинаться с `/api/v1/...` (canonical backend path).
 *
 * При 4xx/5xx — `ApiError` с status + parsed body.
 * При network error — bubble through (fetch native exception).
 *
 * **Refresh token flow (#161)**: на browser-side при 401 → один retry
 * через `/api/auth/refresh` (swap'ает access_token cookie). SSR retry
 * НЕ делаем — Server Components не имеют lifecycle для re-render'а
 * после mutation cookie; SSR caller должен явно handle 401 (redirect).
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  return _doFetch<T>(path, init, /* allowRefresh */ !isServer());
}

async function _doFetch<T>(
  path: string,
  init: RequestInit | undefined,
  allowRefresh: boolean,
): Promise<T> {
  const headers = await buildHeaders(init?.headers);
  const url = buildUrl(path);
  const response = await fetch(url, { ...init, headers });
  if (response.status === 401 && allowRefresh) {
    // Token expired или revoked; try refresh once. На success — retry
    // original request с свежим cookie. На refresh failure — fall through
    // в ApiError(401); caller redirect'нет на /login.
    const refreshed = await tryRefresh();
    if (refreshed) {
      return _doFetch<T>(path, init, /* allowRefresh */ false);
    }
  }
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text().catch(() => null);
    }
    throw new ApiError(response.status, body);
  }
  // 204 No Content или empty body (например, 201 от feedback) → undefined.
  // Caller с `Promise<void>` сигнатурой обработает корректно.
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

/**
 * Обновить access_token cookie через `/api/auth/refresh` (#386).
 *
 * Browser-only helper. Экспортируется, чтобы SSE-путь чата
 * (`streamMessage` в `chat.ts`) мог переиспользовать тот же
 * refresh-on-401, что и `apiFetch` — без импорта `_private`.
 * Возвращает `true` если refresh удался (свежий cookie выставлен).
 */
export async function tryRefresh(): Promise<boolean> {
  try {
    const prefix = BASE_PATH;
    const r = await fetch(`${prefix}/api/auth/refresh`, {
      method: "POST",
      cache: "no-store",
    });
    return r.ok;
  } catch {
    return false;
  }
}

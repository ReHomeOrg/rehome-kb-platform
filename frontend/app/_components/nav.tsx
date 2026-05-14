/**
 * Top navigation bar (UI.1 #75) — Server Component.
 *
 * Reads `kb_session` cookie server-side для auth state, renders
 * Login/Logout button + main links на разделы.
 *
 * Используется как shared header в pages (`app/page.tsx`, `app/articles/...`,
 * etc.). Не в `layout.tsx` (тот глобальный — landing page не имеет nav).
 *
 * Можно вынести в (app) route group когда появится больше pages.
 */

import { cookies } from "next/headers";

import { COOKIE_SESSION } from "@/lib/auth/cookies";

const NAV_LINKS: ReadonlyArray<{ href: string; label: string }> = [
  { href: "/", label: "Главная" },
  { href: "/articles", label: "Статьи" },
  { href: "/documents", label: "Документы" },
  { href: "/chat", label: "Чат" },
  { href: "/hr", label: "Кадры" },
  { href: "/webhooks", label: "Webhooks" },
];

export default async function Nav(): Promise<JSX.Element> {
  const cookieStore = await cookies();
  const isLoggedIn = cookieStore.has(COOKIE_SESSION);

  return (
    <nav className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-6">
          <a href="/" className="font-semibold tracking-tight">
            reHome
          </a>
          <ul className="flex items-center gap-4 text-sm text-gray-700">
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <a
                  href={link.href}
                  className="hover:text-gray-900 hover:underline"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center gap-2">
          {isLoggedIn ? (
            <form action="/api/auth/logout" method="post">
              <button
                type="submit"
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
              >
                Выйти
              </button>
            </form>
          ) : (
            <a
              href="/login"
              className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
            >
              Войти
            </a>
          )}
        </div>
      </div>
    </nav>
  );
}

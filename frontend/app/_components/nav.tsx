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
import Link from "next/link";

import { apiFetch } from "@/lib/api/client";
import { COOKIE_SESSION } from "@/lib/auth/cookies";
import { BASE_PATH } from "@/lib/base-path";
import { PLATFORM_LOGIN_URL, PLATFORM_ORIGIN } from "@/lib/platform";
import { RehomeIdpButton } from "./rehome-idp-button";

/**
 * Признать залогиненного на платформе (rehome.one) юзера по cookie `rh_token`.
 *
 * Help-центр под rehome.one/help делит домен с платформой, поэтому httpOnly
 * `rh_token` (phone-first Django-сессия) доезжает и сюда. Валидируем его на
 * backend (`/auth/platform-session` → platform `/auth/me/`) и, если ок, шапка
 * показывает имя вместо «Войти». Флаг/ключ не выставлены → backend вернёт
 * `authenticated=false`, и мы тихо деградируем к «Войти» (прод-поведение).
 */
async function recognizePlatformUser(rhToken: string): Promise<string | null> {
  try {
    const res = await apiFetch<{ authenticated: boolean; display_name?: string | null }>(
      "/api/v1/auth/platform-session",
      { method: "POST", headers: { "X-RH-Token": rhToken }, cache: "no-store" },
    );
    if (!res?.authenticated) return null;
    return res.display_name?.trim() || "Профиль";
  } catch {
    // Backend недоступен / эндпоинт не задеплоен / токен невалиден — не мешаем
    // рендеру help: просто остаёмся в анонимном виде.
    return null;
  }
}

const NAV_LINKS: ReadonlyArray<{
  href: string;
  label: string;
  authOnly?: boolean;
}> = [
  { href: "/", label: "Главная" },
  { href: "/articles", label: "Статьи" },
  { href: "/premises", label: "Квартиры" },
  { href: "/documents", label: "Документы" },
  { href: "/chat", label: "Чат" },
  { href: "/hr", label: "Кадры", authOnly: true },
  { href: "/webhooks", label: "Вебхуки", authOnly: true },
  { href: "/admin", label: "Админ", authOnly: true },
];

export default async function Nav(): Promise<JSX.Element> {
  const cookieStore = await cookies();
  const isLoggedIn = cookieStore.has(COOKIE_SESSION);
  // Признание платформенной сессии (rehome.one) — только для тех, у кого нет
  // KB-сессии, но есть `rh_token`. Кадры / Вебхуки / Админ остаются гейтнутыми
  // ИМЕННО по KB-сессии (это KB-внутренние разделы, не платформенные).
  const rhToken = isLoggedIn ? undefined : cookieStore.get("rh_token")?.value;
  const platformName = rhToken ? await recognizePlatformUser(rhToken) : null;
  // Кадры / Вебхуки / Админ — только для залогиненных (UX; сами страницы
  // всё равно гейтятся бэкендом по RBAC).
  const visibleLinks = NAV_LINKS.filter(
    (link) => !link.authOnly || isLoggedIn,
  );

  return (
    <nav className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-6">
          {BASE_PATH === "/help" ? (
            // Встроено в платформу (rehome.one/help): значок+надпись reHome
            // как на главной, клик → редирект на главную rehome.one.
            <a
              href="https://rehome.one"
              aria-label="reHome — на главную"
              className="flex items-center gap-2 font-semibold tracking-tight"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="https://rehome.one/assets/locker-logo-mark.jpg"
                alt=""
                width={28}
                height={28}
                className="h-7 w-7 rounded"
              />
              reHome
            </a>
          ) : (
            <Link href="/" className="font-semibold tracking-tight">
              reHome
            </Link>
          )}
          <ul className="flex items-center gap-4 text-sm text-gray-700">
            {visibleLinks.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className="hover:text-gray-900 hover:underline"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center gap-2">
          {isLoggedIn ? (
            <form action={`${BASE_PATH}/api/auth/logout`} method="post">
              <button
                type="submit"
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
              >
                Выйти
              </button>
            </form>
          ) : platformName ? (
            // Узнан по платформенной сессии (rehome.one). KB-сессии нет, поэтому
            // не «Выйти», а имя-ссылка в кабинет платформы.
            <a
              href={`${PLATFORM_ORIGIN}/dashboard`}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
            >
              {platformName}
            </a>
          ) : (
            <>
              <RehomeIdpButton />
              {/* Вход — на платформе (rehome.one), а не в Keycloak help-центра:
                  у прод-пользователей (phone-first) Keycloak-аккаунта нет.
                  Абсолютный URL из origin-корня → не зависит от basePath
                  (прежний `<Link href="/login">` под `/help`-проксёй уезжал в
                  `rehome.one/login` → 404). */}
              <a
                href={PLATFORM_LOGIN_URL}
                className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-ink hover:bg-brand-hover"
              >
                Войти
              </a>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}

/**
 * Layout для /chat/* — Server Component с Nav.
 *
 * Pages в /chat/* — Client Components (нужны useState/useEffect/
 * localStorage/SSE consume). Поэтому Nav (Server Component с next/headers)
 * не может быть импортирован напрямую. Layout фиксит — это Server
 * Component, который монтирует Nav + рендерит children.
 *
 * Auth-гейт: чат доступен только залогиненным пользователям. Анонимам в
 * помощи остаются FAQ и статьи — заход на /chat/* редиректит на /login.
 * Это UX-граница; реальный энфорсмент — на backend (CHAT_REQUIRE_AUTH).
 */

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { COOKIE_SESSION } from "@/lib/auth/cookies";

export default async function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<JSX.Element> {
  const cookieStore = await cookies();
  if (!cookieStore.has(COOKIE_SESSION)) {
    redirect("/login?next=/chat");
  }

  return (
    <>
      <Nav />
      {children}
    </>
  );
}

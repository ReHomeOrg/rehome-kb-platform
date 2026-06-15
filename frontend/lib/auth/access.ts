/**
 * Server-side доступ текущей сессии для UI-видимости (#359).
 *
 * Читает `kb_session` cookie (JWT access_token), декодирует claims БЕЗ
 * верификации подписи (cookie HttpOnly от нашего backend → trusted; то же
 * допущение, что и в `jwt.ts`) и определяет:
 *  - `isLoggedIn` — есть ли сессия;
 *  - `isStaffAdmin` — есть ли realm-роль `staff_admin`.
 *
 * ВАЖНО: это ТОЛЬКО для скрытия/показа элементов UI. Реальная авторизация
 * (edit/delete/create, доступ к ресурсам) enforce'ится бэкендом по
 * access_level/scope (см. backend `auth/dependency.py::require_staff_admin`).
 * Скрытие кнопки не заменяет серверную проверку.
 */

import { cookies } from "next/headers";

import { COOKIE_SESSION } from "./cookies";
import { decodeJwtClaims } from "./jwt";

/** Realm-роль администратора-сотрудника (backend `Scope.STAFF_ADMIN`). */
export const STAFF_ADMIN_ROLE = "staff_admin";

export interface SessionAccess {
  isLoggedIn: boolean;
  isStaffAdmin: boolean;
}

export async function getSessionAccess(): Promise<SessionAccess> {
  const cookieStore = await cookies();
  const token = cookieStore.get(COOKIE_SESSION)?.value;
  if (!token) {
    return { isLoggedIn: false, isStaffAdmin: false };
  }
  const claims = decodeJwtClaims(token);
  const roles = claims?.realm_access?.roles ?? [];
  return { isLoggedIn: true, isStaffAdmin: roles.includes(STAFF_ADMIN_ROLE) };
}

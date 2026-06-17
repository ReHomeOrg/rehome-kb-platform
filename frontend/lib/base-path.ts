/**
 * Базовый путь приложения (basePath). Параметризован через
 * `NEXT_PUBLIC_BASE_PATH` (build-time, инлайнится Next в бандл):
 *
 *   - не задан   → `/help`  — дефолт (Selectel-деплой rehome.one/help);
 *   - `""`       → поддомен-root (help.rehome.one), без basePath;
 *   - `/help`    → явный basePath.
 *
 * Используется ТАМ, где Next НЕ добавляет basePath автоматически:
 *   - `fetch` к route-handlers / proxy (`/api/kb`, `/api/auth/*`);
 *   - `form action` и обычные `<a href>` на route-handlers;
 *   - серверные redirect'ы в route-handlers.
 *
 * Навигационные `<Link>` / `router.push` basePath получают от Next сами —
 * их префиксовать НЕ нужно.
 *
 * `??` (а не `||`) — чтобы пустая строка (поддомен-режим) сохранялась,
 * а не подменялась дефолтом.
 */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "/help";

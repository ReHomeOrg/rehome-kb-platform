/**
 * HTML sanitization для render'а user-derived HTML (UI.2 #77).
 *
 * Используется ТОЛЬКО для backend `SearchHit.snippet` — `ts_headline`
 * Postgres FTS возвращает фрагмент с `<b>...</b>` подсветкой совпадений.
 * **WARNING из backend** (articles/schemas.py): ts_headline НЕ escape'нет
 * existing HTML в body_markdown, поэтому весь snippet проходит DOMPurify
 * с whitelist `<b>` only ДО `dangerouslySetInnerHTML`.
 *
 * isomorphic-dompurify работает и в SSR (jsdom-based) и в browser.
 */

import DOMPurify from "isomorphic-dompurify";

const ALLOWED_TAGS = ["b"] as const;
const ALLOWED_ATTRS = [] as const;

/**
 * Sanitize HTML, оставляя ТОЛЬКО `<b>` теги. Все остальные tags
 * вырезаются, content внутри сохраняется как plain text.
 *
 * Примеры:
 * - `'hello <b>world</b>'` → `'hello <b>world</b>'`
 * - `'<script>alert(1)</script>'` → `''` (script removed)
 * - `'<a href="x">y</a>'` → `'y'` (anchor removed, text kept)
 */
export function sanitizeSearchSnippet(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [...ALLOWED_TAGS],
    ALLOWED_ATTR: [...ALLOWED_ATTRS],
  });
}

# reHome KB Frontend

Frontend для модулей kb-help, kb-staff, kb-hr, kb-vault. Единая Next.js
14 App Router сборка под все суб-домены `*.rehome.one` (см. ПЗ «База
знаний v1.4» раздел 1.4.4 «Единая платформа», ADR-0001).

После UI epic (UI.1-UI.6 / PR #76-#86) — реализованы pages для всех
read-API endpoint'ов backend'а: articles list/search/detail, categories
tree, tags cloud, documents list/detail, chat sessions с SSE streaming.

## Стек

- Next.js 14 (App Router) с TypeScript strict
- React 18+, Tailwind CSS 3
- Vitest + Testing Library + `@vitest/coverage-v8` (порог 60% branches)
- ESLint (`eslint-config-next`)
- `react-markdown@10` + `remark-gfm` + `isomorphic-dompurify` для article render

См. ADR-0001 (категория A, kb-* модули) и ADR-0005 (FastAPI gateway).

## Pages

| Маршрут | Описание | Component type |
|---|---|---|
| `/` | Лендинг help.rehome.one | Server |
| `/login` | OAuth Authorization Code + PKCE flow | Server |
| `/articles` | Список статей с фильтрами + cursor пагинация | Server |
| `/articles/[slug]` | Detail с markdown render | Server |
| `/articles/search` | Постgres FTS поиск с snippet | Server |
| `/categories` | Recursive Category tree → /articles?category= | Server |
| `/tags` | Tag cloud с size scaling → /articles?tags= | Server |
| `/chat` | Список недавних сессий + create | Client |
| `/chat/[session_id]` | Message thread с SSE streaming | Client |
| `/documents` | Список с filter dropdowns | Server |
| `/documents/[id]` | Detail с PII (signed_by, audit_log) | Server |

## Архитектура: API client + proxy

Backend требует `Authorization: Bearer <JWT>`. JWT хранится в HttpOnly
`kb_session` cookie (JS не может прочитать). Поэтому browser-side API
calls идут через Next.js API route proxy:

```
browser → fetch('/api/kb/api/v1/articles')
       → app/api/kb/[...path]/route.ts (читает cookie + добавляет Bearer)
       → backend /api/v1/articles
```

Для SSE — отдельный proxy `/api/kb-sse/<path>` с streaming Response +
`X-Accel-Buffering: no` (nginx-safe).

Для **Server Components** (SSR) — `apiFetch` идёт напрямую через
`BACKEND_BASE_URL + path` + cookie attach через `next/headers.cookies()`.
Hybrid implementation в `lib/api/client.ts`.

## Chat session_token

Anonymous chat sessions identified opaque `session_token` (выдаётся
backend'ом при POST /chat/sessions). Хранится в **localStorage**
(JS-accessible), trade-off: theft = hijack ОДНОЙ chat-сессии (24h
expiry на backend), не user account. Acceptable для MVP. Альтернатива
(HttpOnly cookie + custom proxy) — backlog.

## XSS защита

Двухслойная:
1. **Markdown content** (`react-markdown` 10): default escape raw HTML,
   `rehype-raw` НЕ используется.
2. **Search snippet** (от `ts_headline`): `sanitizeSearchSnippet()` через
   `isomorphic-dompurify` с whitelist `<b>` ONLY перед
   `dangerouslySetInnerHTML`.

## Запуск

```bash
make install     # npm ci, ставит deps по package-lock.json
make dev         # next dev — http://localhost:3000
```

Должен быть запущен backend (uvicorn на 8000 — см. `../backend/Makefile`).

## Проверки

```bash
make lint        # ESLint
make typecheck   # tsc --noEmit (strict)
make test        # Vitest run + coverage (порог 60% по ТЗ 8.3 для UI)
make build       # Next.js production build

# Playwright E2E (#151, smoke tests):
npm run e2e:install   # one-time: скачивает Chromium browser (~140MB)
npm run e2e           # запуск smoke tests против dev server (auto-spawn)
npm run e2e:ui        # UI mode для разработки тестов
```

## Переменные окружения

| Имя | Default | Назначение |
|---|---|---|
| `BACKEND_BASE_URL` | `http://localhost:8000` | Backend API base URL (SSR + proxy) |
| `NEXT_PUBLIC_KC_URL` | `http://localhost:8080` | Keycloak base URL |
| `NEXT_PUBLIC_KC_REALM` | `rehome` | Keycloak realm |
| `NEXT_PUBLIC_KC_CLIENT_ID` | `rehome-web-spa` | OAuth client_id (SPA) |
| `KC_REDIRECT_URI` | `http://localhost:3000/api/auth/callback/keycloak` | OAuth callback URI |
| `KC_POST_LOGOUT_URI` | `http://localhost:3000/` | Post-logout redirect |

## Auth flow

OAuth 2.0 Authorization Code + PKCE (RFC 7636) — manual implementation
без NextAuth.js. См. ADR-0007 для обоснования и Issue #19 для деталей.

```
Browser → /login (UI page)
       → GET /api/auth/login
           - generate PKCE verifier + state
           - set short-lived HttpOnly cookies (5 min)
           - 302 to Keycloak /auth
       → Keycloak login form → user authenticates
       → GET /api/auth/callback/keycloak?code=...&state=...
           - validate state vs cookie (OAuth-CSRF protection)
           - POST /token (code + code_verifier)
           - set kb_session HttpOnly cookie (TTL = expires_in)
           - 302 to /
       → POST /api/auth/logout
           - delete kb_session cookie
           - 302 to Keycloak /logout
```

## Структура

```
frontend/
├── app/
│   ├── layout.tsx               корневой layout, ru локаль
│   ├── error.tsx                global error boundary
│   ├── global-error.tsx         fallback при падении layout.tsx
│   ├── loading.tsx              global loading skeleton
│   ├── page.tsx                 лендинг
│   ├── _components/nav.tsx      top navigation (Server)
│   ├── api/
│   │   ├── auth/                Keycloak OAuth callback routes
│   │   ├── kb/[...path]/        backend API proxy (catch-all)
│   │   └── kb-sse/[...path]/    SSE proxy для chat streaming
│   ├── articles/                list/search/[slug] + loading
│   ├── categories/              recursive tree
│   ├── tags/                    tag cloud
│   ├── chat/                    sessions + thread + SSE consume
│   └── documents/               list + detail (download deferred)
├── lib/
│   ├── api/
│   │   ├── client.ts            apiFetch + ApiError
│   │   ├── types.ts             handwritten TS types backend Pydantic
│   │   ├── articles.ts / chat.ts / categories.ts / tags.ts / documents.ts
│   ├── auth/                    Keycloak helpers (E1.3.3)
│   ├── chat-storage.ts          localStorage helpers для session_token
│   ├── env.ts                   env validation
│   └── sanitize.ts              DOMPurify wrapper для search snippet
├── vitest.config.ts             Vitest + jsdom + coverage v8
└── Makefile                     proxy команд
```

## Backlog после landing UI epic

- **Playwright E2E** — foundation landed в #151 (smoke tests для /login
  + 404). Backend-зависимые сценарии (auth flow, article view, chat
  message, document detail) + CI integration с full stack — follow-up.
- **Dark mode** — Tailwind dark: prefix variants.
- **a11y review** — axe-core в CI, aria-labels checks.
- **i18n** — пока только русский (single language).
- **Generated TS types** из OpenAPI через `openapi-typescript-codegen`
  (сейчас handwritten).
- **React Query / SWR** — pre-fetch + cache. Сейчас Server Components
  с revalidate cover most cases.
- **Refresh token flow** — backend выдаёт access_token TTL ≈ 5 min;
  после expire — 401, нужен retry с refresh. Сейчас просто 401 в UI.
- **Singleton API client** — sharable httpx-like fetch instance с
  connection pooling, retry policy.
- **Linkable search results** — backend `SearchHit` нужен `slug` или
  detail-by-id endpoint (сейчас search показывает results без link на
  detail page).

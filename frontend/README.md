# reHome KB Frontend

Frontend для модулей kb-help, kb-staff, kb-hr, kb-vault. Единая Next.js
14 App Router сборка под все суб-домены `*.rehome.one` (см. ПЗ «База
знаний v1.4» раздел 1.4.4 «Единая платформа», ADR-0001).

На E1.2 (этом PR) — только scaffold: один лендинг help-центра. Реальный
контент и интеграция с API gateway появятся в E2-E3.

## Стек

- Next.js 14 (App Router)
- React 18+
- TypeScript strict
- Tailwind CSS 3
- Vitest + Testing Library + `@vitest/coverage-v8`
- ESLint (`eslint-config-next`)

См. ADR-0001 (категория A, kb-* модули) и ADR-0005 (FastAPI gateway,
который этот frontend будет вызывать на E2).

## Запуск

```bash
make install     # npm ci, ставит deps по package-lock.json
make dev         # next dev — http://localhost:3000
```

## Проверки

```bash
make lint        # ESLint
make typecheck   # tsc --noEmit (strict)
make test        # Vitest run + coverage (порог 60% по ТЗ 8.3 для UI)
make build       # Next.js production build
```

## Переменные окружения

| Имя | Default | Назначение |
|---|---|---|
| `NEXT_PUBLIC_KC_URL` | `http://localhost:8080` | Keycloak base URL |
| `NEXT_PUBLIC_KC_REALM` | `rehome` | Realm name |
| `NEXT_PUBLIC_KC_CLIENT_ID` | `rehome-web-spa` | OAuth client_id (SPA) |
| `KC_REDIRECT_URI` | `http://localhost:3000/api/auth/callback/keycloak` | OAuth callback URI (см. ADR-0007) |
| `KC_POST_LOGOUT_URI` | `http://localhost:3000/` | Куда вернуться после logout |
| `NEXT_PUBLIC_KB_API_URL` | _(E2+)_ | Base URL для kb-API gateway (Production: `https://api.rehome.one/kb`) |

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

Backend (PR #18) валидирует `kb_session` cookie через JWKS и вычисляет
scope из `realm_access.roles`.

## Структура

```
frontend/
├── app/
│   ├── layout.tsx       — корневой layout, ru локаль, метаданные
│   ├── page.tsx         — лендинг help.rehome.one (заглушка)
│   ├── page.test.tsx    — smoke-тесты на главную
│   └── globals.css      — Tailwind directives
├── vitest.config.ts     — Vitest + jsdom + coverage v8 (порог 60%)
├── vitest.setup.ts      — @testing-library/jest-dom matchers
├── tsconfig.json        — TypeScript strict
├── tailwind.config.ts   — Tailwind конфиг
├── next.config.mjs      — Next.js конфиг
└── Makefile             — proxy команд
```

## Что НЕ реализовано на E1.2 (defer)

- Подключение к kb-API (`/api/v1/...`) — E2
- Аутентификация / Keycloak — E1.3
- Подмодули kb-staff, kb-hr, kb-vault — E3-E6
- Storybook / UI-kit catalog — позже, когда накопится компонентов
- Playwright E2E — позже, по реальным user flows
- i18n — пока только русский

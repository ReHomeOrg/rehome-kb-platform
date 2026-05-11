# ADR-0007: Keycloak realm structure — `rehome` realm, 2 клиента, 8 ролей

## Статус

- [x] **Принято**
- **Дата:** 2026-05-12
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-11 (Issue #14 в фазе планирования)

## Контекст

Модуль kb-* использует Keycloak self-hosted как единый SSO (ADR-0001
категория B, CLAUDE.md «Технологический стек»). По ПЗ «API базы знаний v1.3»
раздел 2.2 — два режима аутентификации:

- **m2m** (server-to-server): OAuth 2.0 Client Credentials Grant, для
  rehome.one server-side вызовов API gateway
- **browser** (user-facing): HttpOnly cookie с JWT, выдаётся при login
  пользователя через Authorization Code + PKCE

По ПЗ API 2.3 — 8 scope-значений, соответствующих 8 ролям в realm:
`guest, tenant, landlord, agent, staff_support, staff_legal, staff_hr,
staff_admin`. Каждый scope соответствует набору `access_level` из ADR-0003,
который фильтрует данные на уровне хранилища.

Решение по структуре realm влияет на ≥2 модуля (backend, frontend, все
будущие kb-* сервисы), поэтому ADR обязателен по ТЗ 5.5.

## Решение

### Один realm `rehome` для всех модулей kb-*

Все модули (kb-wiki, kb-help, kb-files, kb-vault, kb-staff, kb-hr,
kb-search) живут в одном realm `rehome`. Пользователи и роли — общие.

### Два клиента

1. **`rehome-platform-m2m`** — server-to-server клиент.
   - Protocol: openid-connect
   - Access Type: confidential (с client secret)
   - Service Accounts Enabled: yes
   - Standard Flow: disabled
   - Direct Access Grants: disabled
   - Implicit Flow: disabled
   - Использование: rehome.one server-side и другие backend-ы вызывают
     API gateway от своего имени через Client Credentials Grant.
   - Service-account-пользователь получает realm-role `staff_admin` по
     умолчанию на dev (для prod — отдельное scope-управление, отдельный
     Issue Phase 2).

2. **`rehome-web-spa`** — browser-based клиент для Next.js фронтенда.
   - Protocol: openid-connect
   - Access Type: public (без client secret, защита через PKCE)
   - Standard Flow: enabled
   - PKCE Code Challenge Method: S256
   - Implicit Flow: disabled
   - Direct Access Grants: disabled
   - Service Accounts: disabled
   - Redirect URIs: `http://localhost:3000/api/auth/callback/keycloak`,
     `http://localhost:3000/*` (для local-dev). Prod URI — отдельный
     Issue Phase 2.
   - Web Origins: `http://localhost:3000`

### 8 ролей realm-level

| Роль | Соответствует scope (ПЗ API 2.3) | Описание |
|---|---|---|
| `guest` | guest | Синтетическая. Не назначается реальным пользователям. Backend использует как default при отсутствии токена в запросе (анонимный гость). Хранится в realm для документации scope-системы. |
| `tenant` | tenant | Наниматель |
| `landlord` | landlord | Наймодатель / собственник объекта |
| `agent` | agent | Агент по закреплённым объектам |
| `staff_support` | staff_support | Оператор поддержки |
| `staff_legal` | staff_legal | Юрист |
| `staff_hr` | staff_hr | HR (отдельный, доступ к HR_RESTRICTED) |
| `staff_admin` | staff_admin | Администратор kb-модуля (всё кроме HR_RESTRICTED) |

Роли назначаются пользователю при создании или при онбординге; user-ролевая
матрица детально — в `backend/src/api/auth/scope.py` (E1.3.2).

### JWT claim contract

Keycloak по умолчанию включает в access_token claim:
```json
{
  "realm_access": {
    "roles": ["staff_support", "agent", ...]
  },
  "iss": "http://localhost:8080/realms/rehome",
  "sub": "user-uuid",
  "preferred_username": "...",
  "email": "...",
  "exp": 1234567890
}
```

Backend OIDC middleware (E1.3.2) валидирует JWT по JWKS endpoint,
читает `realm_access.roles[0]` (приоритетная роль) → вычисляет scope.
Никакого custom protocol mapper не требуется — `realm_access.roles`
имеется по умолчанию.

### Local-dev credentials

Все credentials в local-dev: `admin`/`admin` для Admin Console,
`rehome-platform-m2m-local-dev-secret` для m2m client. Это **намеренно
hardcoded** на этой фазе для простоты:
- В `infra/docker-compose.yml` через `${KEYCLOAK_ADMIN_PASSWORD:-admin}`
  — можно переопределить через `infra/.env`
- В `infra/keycloak/realm-export.json` client secret — статичный, для
  prod будет полная регенерация через CLI

Production credentials и secret management — **отдельный Issue Phase 2**:
- Random Admin password при первой загрузке Keycloak
- Client secrets через Kubernetes Secret или vault.rehome.one
- TLS 1.3 на admin и user endpoints
- Backup БД Keycloak в зашифрованное хранилище в РФ

## Альтернативы

1. **Realm-per-module** (отдельные realms для kb-help, kb-staff, kb-vault и
   т.д.) — отклонено: cross-realm SSO в Keycloak требует «identity provider
   federation», что добавляет сложность и латентность. Один realm проще.

2. **Единый универсальный клиент** (один client для m2m + browser)
   — отклонено: security-профили принципиально разные (confidential vs
   public, PKCE vs Client Credentials), смешивать opasно.

3. **Custom protocol mapper `realm_access.roles` → top-level `roles`**
   — отклонено: добавляет настройку без ценности. `realm_access.roles`
   уже стандартный путь, backend может его читать напрямую.

4. **Federated identity provider** (Login через rehome.one main платформу
   как IDP) — defer на E1.3.5+ или Phase 2. На текущей фазе пользователи
   живут в Keycloak realm локально.

5. **Auth0 / Okta / другие SaaS IdP** — отвергнуто ADR-0001 (категория C,
   минимизируем внешние сервисы).

## Последствия

### Положительные

- Один realm — один admin login, один backup, единые роли
- Стандартный Keycloak setup без кастомизации mappers
- Service-account паттерн для m2m — индустриальный стандарт
- PKCE для SPA — современный browser-flow без implicit grant

### Отрицательные / компромиссы

- Hardcoded credentials в local-dev — explicit риск, требует
  компенсирующего prod-Issue Phase 2 (см. выше)
- Один realm — единая точка отказа для всех модулей; митигация —
  Keycloak HA + Postgres replication в prod (Phase 2)
- Service-account m2m с `staff_admin` ролью на dev — широкие права;
  на prod scope-управление более точное (отдельный Issue Phase 2)

### Технические следствия

- В `backend/src/api/` появится `auth/` модуль с OIDC middleware
  (E1.3.2)
- В `frontend/` появится NextAuth.js конфигурация или явный OIDC client
  (E1.3.3)
- В CI security-тесты на попытки обхода прав (E2-E3)
- Production deployment (Phase 2) потребует:
  - Регенерацию admin password при первой загрузке
  - Хранение client secret в Secret-manager (не в realm-export.json)
  - TLS 1.3 на 8080
  - Postgres replication + бэкапы в РФ
  - Регистрация Keycloak instance в Роскомнадзоре как ПО, обрабатывающее
    ПДн (см. ПЗ «База знаний v1.4» раздел 4.2.6)

## Ссылки

- Issue: https://github.com/rehome-one/kb-platform/issues/14
- ПЗ: «API базы знаний v1.3» разделы 2.2 (auth modes), 2.3 (scope ↔ роли)
- ПЗ: «База знаний v1.4» разделы 1.4.2 (Keycloak в стеке), 4.2 (ФЗ-152)
- ADR-0001 (стек), ADR-0003 (двухконтурность), ADR-0005 (FastAPI gateway)
- Внешние:
  - [Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/)
  - [OAuth 2.0 Client Credentials Grant (RFC 6749 §4.4)](https://datatracker.ietf.org/doc/html/rfc6749#section-4.4)
  - [PKCE for OAuth Public Clients (RFC 7636)](https://datatracker.ietf.org/doc/html/rfc7636)

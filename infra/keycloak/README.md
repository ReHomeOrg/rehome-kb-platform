# Keycloak (local-dev)

Локальная конфигурация Keycloak self-hosted для разработки kb-auth и
других модулей kb-*, использующих OIDC. Это **только** local-dev; production
deployment — отдельный Issue Phase 2 (см. ADR-0007 «Production credentials»).

## Запуск

Из корня репозитория:

```bash
cd infra
cp .env.example .env     # опционально: правьте дефолты при необходимости
docker compose up -d keycloak postgres-keycloak
```

Первый старт — около 30-60 секунд (Postgres init + realm import).

### URLs

| Назначение | URL |
|---|---|
| Admin Console | http://localhost:8080 (login: `admin`/`admin` по умолчанию) |
| Realm discovery | http://localhost:8080/realms/rehome/.well-known/openid-configuration |
| Token endpoint | http://localhost:8080/realms/rehome/protocol/openid-connect/token |
| JWKS endpoint | http://localhost:8080/realms/rehome/protocol/openid-connect/certs |
| Health (management port) | http://localhost:9000/health/ready |

## Структура realm

См. ADR-0007 для обоснования.

- Realm: `rehome`
- Клиенты:
  - `rehome-platform-m2m` (Client Credentials grant, service account)
  - `rehome-web-spa` (Authorization Code + PKCE)
- Роли realm (8): `guest`, `tenant`, `landlord`, `agent`, `staff_support`,
  `staff_legal`, `staff_hr`, `staff_admin`
- Сервис-аккаунт `service-account-rehome-platform-m2m` имеет роль
  `staff_admin` (на dev — для удобства; на prod — точное scope-управление)

## Smoke-test

После запуска проверьте, что всё работает:

```bash
./keycloak/smoke-test.sh
```

Скрипт делает 4 проверки:
1. Keycloak ready
2. Realm discovery
3. m2m Client Credentials grant
4. JWT содержит роль `staff_admin` в `realm_access.roles`

Exit 0 если всё OK, !=0 если что-то сломалось.

## Изменение realm

`realm-export.json` импортируется автоматически при старте Keycloak
(флаг `--import-realm` в `docker-compose.yml`). Если вы меняли realm
через Admin Console и хотите сохранить изменения:

```bash
# Из контейнера экспортнуть realm в файл
docker compose exec keycloak \
  /opt/keycloak/bin/kc.sh export \
  --realm rehome \
  --file /opt/keycloak/data/import/realm-export.json \
  --users skip
```

Опция `--users skip` критична — она исключает реальных пользователей из
экспорта (защита от утечки ПДн / dev-credentials в репозиторий).

После экспорта — `git diff infra/keycloak/realm-export.json` и коммит.

## Полная очистка

Удалить volume с Postgres-данными Keycloak (потеряете всё):

```bash
cd infra
docker compose down -v
```

## Переменные окружения

См. `infra/.env.example`. Файл `infra/.env` — не в git (см. корневой
`.gitignore`).

## Production deployment

Отдельный Issue в Phase 2. Чек-лист:

- [ ] Random Admin password при первой загрузке
- [ ] Client secrets через Kubernetes Secret / vault.rehome.one
- [ ] TLS 1.3 на admin и user endpoints
- [ ] HA: 2+ инстанса Keycloak за балансировщиком
- [ ] Postgres replication + бэкапы в РФ
- [ ] Регистрация Keycloak instance в Роскомнадзоре как ПО, обрабатывающее
      ПДн (ПЗ «База знаний v1.4» раздел 4.2.6)
- [ ] Audit log retention ≥5 лет

## Ссылки

- ADR-0007: `docs/adr/0007-keycloak-realm-structure.md`
- ПЗ «API базы знаний v1.3» раздел 2.2 (auth modes), 2.3 (scope ↔ роли)
- Keycloak docs: https://www.keycloak.org/docs/latest/server_admin/

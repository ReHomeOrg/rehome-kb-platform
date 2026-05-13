# reHome Knowledge Base — модуль базы знаний платформы reHome

> Цифровая платформа долгосрочной аренды жилья. ООО «РЕХОМ», Санкт-Петербург.

Этот репозиторий содержит модуль базы знаний reHome:
- Wiki (внутренние и публичные статьи)
- Help-центр для пользователей rehome.one
- Хранилище юридических и операционных документов
- Менеджер паролей и доступов
- Реестр карточек квартир
- Кадровый портал
- AI-чат поверх базы знаний (RAG)
- Реестр коллаборантов (УК/ТСЖ, клининг, ремонт и др.)
- API для подключения к платформе rehome.one

## Старт работы

### Если вы — Claude Code

1. Прочитайте `CLAUDE.md` (Разработчик) или `CLAUDE-REVIEWER.md` (Проверяющий).
2. Прочитайте документы постановки задачи в `docs/handoff/01_postanovka/`.
3. Изучите архитектурные решения в `docs/adr/`.
4. Следуйте процессу из `docs/handoff/02_process/`.

### Если вы — человек, впервые открывший репозиторий

1. Прочитайте `docs/handoff/HANDOFF.md`.
2. Изучите `docs/architecture.md` для понимания общей структуры.
3. Запустите локальный dev-стенд (см. ниже).

## Архитектура

Модуль базы знаний — единая платформа из нескольких приложений:

- `kb-wiki` — внутренняя wiki (Django + Postgres FTS)
- `kb-help` — публичный help-центр (Next.js SSR)
- `kb-files` — хранилище документов (FastAPI + MinIO)
- `kb-vault` — менеджер паролей (security-критичный)
- `kb-staff` — админка (Next.js + Django REST)
- `kb-hr` — кадровый портал
- `kb-search` — RAG-движок AI-чата (FastAPI + Qdrant)
- `kb-eval` — eval-стенд для LLM
- `kb-auth` — общая аутентификация (Keycloak)
- `kb-api-gateway` — единая точка API (FastAPI)

Подробности — в `docs/architecture.md` и ADR.

## Стек

**Backend:** Python 3.12+, Django 5, FastAPI, Dramatiq, PostgreSQL 16 + pgvector,
Qdrant, MinIO, Redis, Keycloak.

**Frontend:** Next.js 14+, React 18+, TypeScript strict, Tailwind CSS.

**Принцип:** «разрабатываем сами». Внешние сервисы — только критически
необходимый минимум (банк, KYC, SMS, КЭП, 1С:ЗУП, ЭДО). См. ADR-0001.

## Локальный dev-стенд

Инфраструктурные сервисы (Keycloak, в будущем Postgres основной БД, Redis,
Qdrant, MinIO) разворачиваются через `infra/docker-compose.yml`. Сейчас
доступны только Keycloak + Postgres backend для Keycloak (E1.3.1, остальное
по мере прохождения эпиков):

### Требования

- `docker` + `docker compose` v2.
- `sops` ≥ 3.9 + `age` (см. ADR-0009 secrets management) — для расшифровки secrets.
- `python` 3.12 / `node` 20 — для backend / frontend.
- `make` (обёртки для daily-dev commands).

### Установка sops + age

```bash
# macOS:
brew install sops age

# Ubuntu/Debian:
sudo apt-get install age
sudo curl -L https://github.com/getsops/sops/releases/latest/download/sops-v3.9.1.linux.amd64 -o /usr/local/bin/sops
sudo chmod +x /usr/local/bin/sops
```

### Onboarding (первый запуск)

1. **Получите dev age private key** у Architect'а (DM / 1Password /
   физический exchange — НЕ через публичные каналы). Положите в
   `~/.config/sops/age/keys.txt` (стандартный путь, sops читает без
   дополнительной конфигурации).

2. **Decrypt dev secrets → `.env.local`** (в repo root, gitignored, mode 600):

   ```bash
   make -C infra decrypt-dev
   ```

   Helper-target проверяет sops+age + age key reachable; fail'ится loudly
   на любую проблему вместо silent fallback.

3. **Запустите infra stack:**

   ```bash
   make -C infra up
   # Сервисы:
   #   Keycloak  → http://localhost:8080
   #   Postgres  → localhost:5432
   ```

4. **Backend:**

   ```bash
   cd backend
   make install
   make migrate    # alembic upgrade head
   make run        # uvicorn → http://localhost:8000/api/v1/health
   ```

5. **Frontend:**

   ```bash
   cd frontend
   make install
   make dev        # next dev → http://localhost:3000
   ```

### Daily-dev cheat sheet

```bash
make -C infra up                       # старт compose stack
make -C infra down                     # стоп
make -C infra logs SERVICE=keycloak    # tail логов
make -C infra edit-dev                 # in-place sops edit dev secrets
make -C infra encrypt-dev FILE=...     # добавить новые secrets из plain yaml
```

### Secrets management

См. [ADR-0009](docs/adr/0009-secrets-management.md) и
[deploy/secrets/README.md](deploy/secrets/README.md). Кратко:

- Plain-text `.env*` — **никогда** в git (`.gitignore` enforce'ит).
- Все environment secrets живут encrypted в `deploy/secrets/<env>.enc.yaml` (SOPS + age).
- Compose `${VAR:?required}` для secrets — startup fail'ится fast если
  variable не выставлена (no silent fallback на embedded passwords).
- Age private key custody, rotation policy — issue
  [#118](https://github.com/rehome-one/rehome-kb-platform/issues/118).

### Без docker-compose

Backend unit-тесты не требуют compose:

```bash
cd backend && make install && make test
```

Integration tests требуют compose + uvicorn (см. CI `Integration (Keycloak)`
job в `.github/workflows/ci.yml`).

## Тестирование

```bash
make test              # все тесты
make test-unit         # только unit
make test-integration  # integration
make test-contract     # контрактные (по OpenAPI)
make test-e2e          # end-to-end через Playwright
make lint              # ruff + eslint + mypy + tsc
```

Покрытие тестами: ≥ 80% для бизнес-логики, ≥ 60% для UI.

## Процесс разработки

Используется двухагентная схема с участием Claude Code:

- **Агент-Разработчик** пишет код по плану.
- **Агент-Проверяющий** ревьюит и одобряет PR.
- **Архитектор** (человек) решает спорные случаи.

Полные правила — в `docs/handoff/02_process/01_ТЗ_двухагентная_разработка.docx`.

Жёсткие правила:
- Защищённые ветки (main, develop) — только через PR с approve Проверяющего.
- Никаких force-push, amend, rebase на защищённых ветках.
- Никаких костылей из списка раздела 5.2 ТЗ.
- Изменение чужого кода — только если это часть текущей задачи.
- ПДн — всегда с шифрованием, логированием, RBAC.
- access_level — фильтрация на уровне хранилища, не приложения.

## Документация

- `docs/handoff/` — пакет ТЗ от заказчика
- `docs/adr/` — Architecture Decision Records
- `docs/architecture.md` — обзор архитектуры
- `docs/glossary.md` — глоссарий проекта
- `docs/consumers.md` — карта потребителей API
- `docs/state-of-code.md` — состояние кода (артефакт Phase 0)
- `docs/phase-reviews/` — ревью каждой фазы разработки
- `CHANGELOG.md` — журнал изменений
- `OpenAPI Swagger UI` — http://localhost:8000/kb/api/v1/docs (после запуска)

## Безопасность и ФЗ-152

Платформа обрабатывает персональные данные. Соответствие ФЗ-152 — обязательное:

- Все серверы в РФ.
- Шифрование в покое (AES-256) и в передаче (TLS 1.3).
- Логирование операций с ПДн в audit_log.
- Право на удаление (`DELETE /api/v1/chat/sessions/{id}`).
- Уведомление РКН о составе данных.

При обнаружении уязвимости — security@rehome.one. Не публикуйте в публичных каналах.

## Лицензия

Proprietary. Все права принадлежат ООО «РЕХОМ».

## Контакты

- **Архитектор проекта:** <ФИО> <контакт>
- **DevOps:** <ФИО> <контакт>
- **Юрист (ФЗ-152, договоры):** <ФИО> <контакт>

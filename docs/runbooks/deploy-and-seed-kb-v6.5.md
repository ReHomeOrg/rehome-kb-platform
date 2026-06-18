# Runbook: деплой + сидинг KB v6.5 на prod (help.rehome.one)

> Цель: доставить контент мастер-документа `backend/scripts/seed/reHome_KB_master_v6.5.md`
> (241 статья с кликабельными ссылками + 15 категорий + 9 юр-документов) и текущий код
> `main` на prod-окружение help.rehome.one.

## Важные особенности (читать до начала)

- **Деплой ручной**: workflow `Build & Deploy KB Platform` (`workflow_dispatch`). Образы —
  в Selectel CR (`cr.selcloud.ru/rehome`), тег = `${GITHUB_SHA::7}`.
- **Сервер**: SSH на секрет `HOST`, рабочая директория `/app`, compose-проект `-p prod`,
  env-файл `/opt/rehome/prod/.env`, сервисы `postgres-kb`, `kb-backend`, `kb-frontend`.
  ⚠️ В `CLAUDE.md` указан `HOST=95.213.154.92`, но DNS `help.rehome.one → 93.77.180.57` —
  **сверить актуальный секрет `HOST` перед деплоем** (возможен прокси/смена сервера).
- **Штатный сид деплоя = `src.api.db.seed_kb`** (docx из bucket `kb-seed`, ADR-0027), он
  **НЕ** запускает v6.5-скрипты — их прогоняем вручную (шаг 3).
- **Backend-образ должен содержать `scripts/`** (см. prerequisite-PR: `COPY scripts ./scripts`
  в `backend/Dockerfile`). Без этого шаги 3.x и deploy-step `reindex_articles` не работают.
- Prod-слаги существующих статей имеют суффикс `-NNN`, слаги v6.5 — без него. Поэтому
  чистка старого корпуса (шаг 4) = **полная замена** статей; требует решения Архитектора.

## 0. Пред-полётная подготовка

1. Сверить секрет `HOST` с реальным prod-сервером.
2. Проверить `/app/docker-compose.yml` и `/opt/rehome/prod/.env` (DB-креды +
   `S3_ENDPOINT` / `S3_KEY` / `S3_SECRET` для документов).
3. **Бэкап БД (ОБЯЗАТЕЛЬНО)**:
   ```bash
   ssh <prod> 'cd /app && docker compose -p prod --env-file /opt/rehome/prod/.env exec -T \
     postgres-kb pg_dump -U <db_user> rehome_kb' > rehome_kb_$(date +%F).sql
   ```
4. Зафиксировать текущее состояние:
   ```bash
   docker compose -p prod --env-file /opt/rehome/prod/.env exec -T postgres-kb \
     psql -U <u> -d rehome_kb -tAc \
     "SELECT (SELECT count(*) FROM articles), (SELECT count(*) FROM categories), (SELECT count(*) FROM documents);"
   ```

## 1. Prerequisite: `scripts/` в backend-образе

Реализовано в этом же PR (`COPY --chown=app:app scripts ./scripts` в `backend/Dockerfile`).
Убедиться, что `backend/.dockerignore` не исключает `scripts/seed/*.md`. Смержить в `main`
с зелёным CI — иначе шаги 3.x и `python -m scripts.*` в контейнере упадут.

## 2. Деплой текущего `main`

```bash
gh workflow run "Build & Deploy KB Platform" --ref main
```
Pipeline: build+push образов (тег `${SHA::7}`) → SSH → `docker compose pull kb-backend kb-frontend`
→ `up -d --no-deps postgres-kb kb-backend kb-frontend` → `alembic upgrade head` (схема уже на
`0034_chat_unanswered_queries`, no-op) → `seed_kb` (штатный) → `reindex_articles`.
Дождаться зелёных `build-and-push` → `deploy-prod`.

## 3. Сидинг контента v6.5 (вручную, в контейнере `kb-backend`)

Порядок обязателен: **категории → статьи → документы → переиндексация**.

```bash
ssh <prod>; cd /app
ENV='-p prod --env-file /opt/rehome/prod/.env'

# 3.1 Категории (15, create-missing)
docker compose $ENV exec -T kb-backend \
  python -m scripts.seed_kb_categories scripts/seed/reHome_KB_master_v6.5.md

# 3.2 Статьи (241, direct-db; инлайн-ссылки → кликабельные названия)
docker compose $ENV exec -T kb-backend \
  python -m scripts.import_kb_markdown scripts/seed/reHome_KB_master_v6.5.md --direct-db

# 3.3 Документы (9; нужен prod-S3/MinIO). Креды читаем из /opt/rehome/prod/.env
#     теми же ключами, что и deploy.yml (S3_ENDPOINT_URL/S3_ACCESS_KEY/S3_SECRET_KEY),
#     и мапим в MINIO_* идентично пайплайну (стрип протокола + detect secure).
#     Предварительно убедиться, что bucket rehome-kb-files существует.
ENVFILE=/opt/rehome/prod/.env
S3_ENDPOINT="$(grep '^S3_ENDPOINT_URL=' $ENVFILE | cut -d= -f2- | tr -d '\"'"'"')"
S3_KEY="$(grep '^S3_ACCESS_KEY=' $ENVFILE | cut -d= -f2- | tr -d '\"'"'"')"
S3_SECRET="$(grep '^S3_SECRET_KEY=' $ENVFILE | cut -d= -f2- | tr -d '\"'"'"')"
MINIO_HOST="$(echo "$S3_ENDPOINT" | sed -e 's|^https\?://||')"
echo "$S3_ENDPOINT" | grep -q '^https' && MINIO_SECURE=True || MINIO_SECURE=False

docker compose $ENV exec -T \
  -e MINIO_ENABLED=True \
  -e MINIO_ENDPOINT="$MINIO_HOST" \
  -e MINIO_ACCESS_KEY="$S3_KEY" \
  -e MINIO_SECRET_KEY="$S3_SECRET" \
  -e MINIO_BUCKET=rehome-kb-files \
  -e MINIO_SECURE="$MINIO_SECURE" \
  kb-backend python -m scripts.import_kb_documents scripts/seed/reHome_KB_master_v6.5.md

# 3.4 Переиндексация для семантического поиска
docker compose $ENV exec -T kb-backend python -m scripts.reindex_articles
```

Идемпотентность: `import_kb_markdown` — upsert по slug; `import_kb_documents` — skip по title;
`seed_kb_categories` — create-missing. Повторный прогон безопасен. `MINIO_BUCKET` должен
совпадать с тем, из которого backend читает файлы (его prod `.env`), иначе документы не
скачаются через приложение.

## 4. (Опционально) Чистка старых статей не из v6.5 — ⚠️ решение Архитектора

На prod ~213 статей со слагами `…-NNN`; ни один не совпадёт со слагами v6.5 → удалится
**весь старый корпус** (замена на 241 v6.5). Делать ТОЛЬКО после бэкапа (шаг 0) и явного
согласования.

```bash
docker compose $ENV exec -T kb-backend python - <<'PY'
import asyncio
from pathlib import Path
async def m():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from src.api.config import get_settings
    from scripts.import_kb_markdown import parse_articles
    keep = list({a["slug"] for a in parse_articles(Path("scripts/seed/reHome_KB_master_v6.5.md"))})
    e = create_async_engine(get_settings().database_url)
    async with e.begin() as c:
        r = await c.execute(text("DELETE FROM articles WHERE NOT (slug = ANY(:s))"), {"s": keep})
        print("удалено:", r.rowcount)
    await e.dispose()
asyncio.run(m())
PY
# затем повторить 3.4 reindex
```
FK `article_versions` / `article_embeddings` / `article_questions` — `ON DELETE CASCADE`,
сирот не будет.

## 5. Верификация на help.rehome.one

- Главная: **15 блоков-категорий** с иконками, включая 🤝 Агенты / ⚖️ Споры / 📖 Глоссарий /
  🛟 Поддержка.
- Статья с отсылкой: «см. статью **[Название]**» кликабельно → `/articles/<slug>`.
- Раздел Документы: 9 документов; скачивание под авторизацией (presigned, не 503).
- Чат/семантический поиск возвращает статьи v6.5.

```bash
curl -s https://help.rehome.one | grep -oE '🤝|⚖️|📖|🛟' | sort -u   # иконки 12–15
```

## 6. Откат

- **Код**: перезапустить deploy на предыдущем SHA (или `docker compose pull/up` с прежним
  тегом образа).
- **Данные**: восстановить из бэкапа шага 0 (`psql < rehome_kb_<дата>.sql`).

## Чек-лист

- [ ] Секрет `HOST` сверен с реальным prod
- [ ] Бэкап БД снят до сидинга
- [ ] Prerequisite-PR (`scripts/` в образе) смержён и задеплоен
- [ ] Prod-S3 bucket `rehome-kb-files` существует
- [ ] Решение по чистке старого корпуса (шаг 4) принято
- [ ] Окно обслуживания согласовано (деплой перезапускает kb-backend/kb-frontend)

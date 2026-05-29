# ADR-0027: KB seed source-of-truth — MinIO bucket `kb-seed`

## Статус

- [ ] Предложено
- [x] **Принято** — 2026-05-29 Architect Evgeniy
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-29
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** **да**, 2026-05-29
- **Approve note:** Architect approved option A (MinIO bucket) vs B
  (Git LFS) vs C (ops-managed). Подтверждено в Claude Code session
  2026-05-29 после Reviewer backlog item #5.

## Контекст

PR'ы #340 (138 KB-статей) и #343 (Q&A module) импортировали статьи в
production через `backend/scripts/import_kb_articles.py`. Скрипт читал
.docx из hardcoded путей `/home/evgeniy/Downloads/...`, что создавало
два связанных риска:

1. **Reproducibility ноль.** Через 3-6 месяцев никто не сможет
   ответить «откуда взялись эти 138 статей и как воспроизвести
   импорт». Архитекторская машина — не source-of-truth.
2. **Drift detection ноль.** Если Архитектор случайно загрузит другую
   версию .docx, скрипт молча импортирует другой набор без
   уведомления — данные в production «дрейфуют» без следов в Git.

Reviewer 2026-05-28 поднял это как item #5 backlog'а; Архитектор
подтвердил необходимость решения до конца недели.

## Рассмотренные варианты

### A. MinIO bucket `kb-seed` (принято)

Сложить .docx в новый MinIO bucket `kb-seed/articles/<DATE>/`. Скрипт
fetch'ит по умолчанию из `seed://reHome_FAQ_топ15.docx`, который
резолвится в `s3://kb-seed/articles/2026-05-28/...`. Sha256 hashes
pinned в коде; mismatch → SystemExit.

**Плюсы:**

- MinIO уже в стеке (kb-files, ADR-0012). Нулевая новая инфра.
- Весь in-РФ (ФЗ-152 §22 compliant — ПДн в .docx нет, но политика
  «всё в РФ» применима универсально).
- Не раздувает Git clone'ы — .docx это data, не code.
- Sha256 verification даёт hard-fail при drift'е.
- Bump seed-версии — explicit operation (новый префикс + bump PINNED
  hashes в PR), Git history следит за изменениями pinned hash'ей.

**Минусы:**

- Импорт-скрипт теперь требует MinIO env vars (`MINIO_ENABLED`,
  endpoints, ключи). Для dev'а есть `file://` override.
- +~30 LOC tooling (URI resolver + S3 fetch). Низкая поддержка
  cost'а — переиспользуем существующий `get_minio_client`.

### B. Git LFS

Положить .docx в репо через Git LFS.

**Плюсы:**

- Reproducibility без сетевых вызовов. Clone репо → есть seed.
- Git history следит за изменениями binary файлов «бесплатно».

**Минусы:**

- **Новая инфра.** LFS server (own или GitHub LFS) — ещё одна
  зависимость для ради двух файлов в год. Нарушает CLAUDE.md
  «принцип разрабатываем сами» — мы добавляем сервис без явной
  необходимости когда MinIO уже есть.
- LFS на GitHub имеет квоты bandwidth/storage. На self-hosted —
  ещё один сервис в эксплуатации.
- Clone'ы раздуваются у разработчиков, которые seed'ом не
  пользуются (большинство).

### C. Ops-managed (на машине Архитектора + git-ignored)

Оставить статус-кво — Архитектор хранит локально.

**Плюсы:** ноль работы.

**Минусы:** проигрывает обоим критериям (reproducibility, drift
detection). Architect bus-factor = 1. Отклонено.

## Решение

Принят вариант **A**.

Реализация:

1. `backend/scripts/import_kb_articles.py` принимает `--faq <URI>` и
   `--kb <URI>`. URI schemes: `file://`, `s3://bucket/key`,
   `seed://name.docx` (alias для `s3://kb-seed/articles/<SEED_VERSION>/<name>.docx`),
   или абсолютный path.
2. `SEED_VERSION` + `EXPECTED_SHA256` pinned в коде. Mismatch →
   SystemExit с подсказкой про `--no-verify-sha` для legitimate bumps.
3. S3 fetch использует существующий `get_minio_client` (`MinIO_*` env
   vars). Никакого дублирования config'а.
4. `backend/scripts/seed/README.md` документирует bucket layout +
   текущие hashes + операцию bump'а версии.

## Последствия

**Положительные:**

- Reproducibility: `python -m scripts.import_kb_articles` работает
  одинаково на любой машине с MinIO env vars.
- Drift detection: sha256 mismatch — hard fail.
- Bus-factor: любой member команды с MinIO credentials может
  re-import'нуть статьи.

**Отрицательные / следующие шаги:**

- Production должен иметь `kb-seed` bucket созданным до того, как
  кто-то запустит `import_kb_articles` без `file://` override.
  Bucket creation — manual step (или Terraform task, backlog).
- Dev'у без MinIO credentials придётся использовать `file://`
  override — это документировано в README.

## Operations-чеклист (для Архитектора)

- [ ] Создать MinIO bucket `kb-seed` (если не существует):
      `mc mb local-minio/kb-seed`
- [ ] Загрузить текущую seed-версию:
      `mc cp ~/Downloads/reHome_FAQ_топ15.docx local-minio/kb-seed/articles/2026-05-28/`
      `mc cp ~/Downloads/reHome_База_статей_120.docx local-minio/kb-seed/articles/2026-05-28/`
- [ ] Проверить hashes на стороне MinIO совпадают с pinned (mc supports
      `--checksum sha256` при upload).
- [ ] (Опционально) backlog Terraform — bucket creation + IAM policy.

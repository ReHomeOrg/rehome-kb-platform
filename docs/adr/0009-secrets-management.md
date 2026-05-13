# ADR-0009: Secrets management — env vars + SOPS-encrypted at-rest

## Статус

- [ ] **Предложено**
- [ ] Принято
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-13
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** нет (требуется review)

## Контекст

После landing'а observability foundation (#106–#111), readiness probe
(#112) и backend Dockerfile (#114), мы достигли prod-deploy readiness'а на
уровне приложения. Следующий gating-блок — **где живут секреты, как
попадают в pod / контейнер и как ротируются**.

Текущая поверхность секретов (по `backend/src/api/config.py` +
`infra/docker-compose.yml`):

| Секрет | Где используется | Сейчас |
|---|---|---|
| `POSTGRES_KB_PASSWORD` | kb-API → Postgres | `${VAR:-kb}` в compose, env в local-dev |
| `POSTGRES_KEYCLOAK_PASSWORD` | Keycloak → Postgres | то же |
| `KEYCLOAK_ADMIN_PASSWORD` | admin-cli | то же |
| `KC_M2M_CLIENT_SECRET` | m2m client credentials | то же |
| `LLM_VLLM_API_KEY` | vLLM provider | env, optional |
| HMAC `secret` каждого webhook | per-tenant, ФЗ-152 | хранится в `webhooks.secret` (Postgres) |
| Будущие: MinIO creds (kb-files), Vault tokens (если выберем Vault) | разные | — |

Ограничения:

1. **ФЗ-152**: все серверы и persisted credentials — в РФ. SaaS-vault'ы
   AWS Secrets Manager / Azure Key Vault / GCP Secret Manager **исключены**.
2. **Self-hosted bias** (CLAUDE.md «Технологический стек»: «Прежде чем
   добавлять новую внешнюю зависимость — проверь, можно ли решить задачу
   существующим самописным кодом или open-source self-hosted»).
3. **Команда compact** — операционный overhead Vault'а (rotation
   policies, audit log, HA) сейчас несоразмерен.
4. **Не закрывать дверь** — выбор должен оставлять путь к Vault'у /
   OpenBao'у когда количество секретов / частота ротации это оправдает.
5. **Compose + k8s coexistence** — local-dev на docker-compose, prod
   путь — k8s. Решение должно работать в обоих.

## Решение

**Two-tier подход:**

### Tier 1: Runtime — env vars из orchestrator's secret API

Приложение читает все секреты ТОЛЬКО из env vars (pydantic-settings уже
так устроен — см. `backend/src/api/config.py`). Никакой логики
"загрузить из файла / Vault / etc." в коде приложения — это работа
оркестратора.

- **Local-dev (docker-compose)**: `env_file: .env.local` (gitignored,
  developer's responsibility).
- **CI (GitHub Actions)**: GitHub repository secrets → env vars в job.
- **Prod (k8s)**: native `Secret` resources, mount'нуты как env через
  `envFrom: - secretRef`.

Преимущество: приложение не знает откуда секрет приходит — perfect
изоляция infra от code.

### Tier 2: At-rest — SOPS-encrypted YAML в git

`deploy/secrets/<env>.enc.yaml` — encrypted с
[Mozilla SOPS](https://github.com/getsops/sops) + age key per environment
(`age` — Go-implementation, simpler than PGP). Decryption происходит:

- **На разработчике**: `sops decrypt deploy/secrets/dev.enc.yaml` →
  `.env.local` (gitignored).
- **На CI/CD job**: age private key из GitHub secret →
  `sops decrypt | kubectl apply` либо `sops decrypt > .env && docker-compose up`.
- **В k8s через kustomize**: `kustomize-sops` plugin при `kubectl apply -k`.

Решает «где секреты живут в git-репозитории» без runtime infrastructure:
**нет Vault'а, который надо ставить, поддерживать, делать HA, бэкапить**.

### Где НЕ применяется SOPS — runtime-сгенерированные секреты

Webhook HMAC `secret` (`backend/src/api/webhooks/repository.py:21`)
генерируется per-tenant при создании webhook'а и живёт в Postgres. Это
**application data**, не infrastructure secret — SOPS его не касается.

DB-storage этих secret'ов уже зашифрован на уровне disk encryption (см.
ADR-0001 раздел 5 ФЗ-152). Future: pgsodium / pgcrypto column-level
encryption — отдельный ADR.

### Git hygiene

- `.gitignore`: `*.env`, `*.env.*` (кроме `*.enc.yaml`).
- Pre-commit hook (см. ниже): TruffleHog scan на новых commit'ах. Уже
  стоит в CI security-scan job — pre-commit duplicate'ит локально.
- `.sops.yaml` в repo root объявляет creation rules (какие age keys
  шифруют какие пути).

## Альтернативы

1. **HashiCorp Vault / OpenBao self-hosted** — отклонена потому что
   операционный overhead (HA, audit, key rotation, unsealing) превышает
   текущий benefit. Repeated upgrade-pain точно прилетит до того как
   secret count перерастёт SOPS-практичность. Reservation: ADR-0009b может
   reopen этот выбор когда secret count >50 или появится compliance
   requirement audit-log'а доступа к secret'ам.

2. **k8s Secrets only (без encryption at-rest в git)** — отклонена потому
   что secrets всё равно должны быть SOMEWHERE persisted между deploy'ями
   (developer onboarding, disaster recovery, environment promotion).
   Хранить их «где-то в Notion'е» или 1Password vault'е раздваивает
   source of truth и плохо аудитится. SOPS-encrypted в git — single source
   of truth, history audit'ится как обычные diff'ы.

3. **AWS Secrets Manager / Azure Key Vault / Yandex Cloud Lockbox** —
   AWS/Azure отклонены by ФЗ-152 (не РФ). Yandex Lockbox потенциально
   возможен но: (a) vendor lock-in на YC, (b) дороже SOPS at low volume,
   (c) сложнее dev environment'ы (нужен YC IAM).

4. **dotenv-vault / Doppler** — SaaS solutions с frontend interface. Те
   же ФЗ-152 + vendor lock-in возражения.

5. **Pure env vars + no encryption** (status quo + просто «не клади
   secrets в repo») — отклонена потому что:
   - Onboarding каждого нового developer'а: где он берёт `.env.local`?
     Slack DM от tech lead'а? Не аудитится.
   - Disaster recovery: если оригинальный operator уехал — где prod
     secrets? «У него в head'е» не план.
   - SOPS — это просто формализация уже неизбежной practice, без
     runtime infra cost.

## Последствия

### Положительные

- **Zero runtime infra debt** — нет Vault'а, который нужно эксплуатировать.
- **Single source of truth** — `deploy/secrets/*.enc.yaml` в repo.
- **Git history** — кто/когда менял secret, аудитится через `git log`.
- **Standard tooling** — SOPS + age — широко используются в k8s/GitOps
  community (Flux, ArgoCD имеют native SOPS-support).
- **Migration path** — переход на Vault позже не требует изменений в
  application code (env vars остаются env vars).
- **Compose + k8s одна модель** — оба orchestrator'а потребляют env vars
  finally generated через `sops decrypt`.

### Отрицательные / компромиссы

- **Manual rotation** — нет automatic credential rotation (как у Vault).
  Operator переписывает `*.enc.yaml`, commit'ит, redeploy'ит.
  Acceptable пока количество secrets низкое.
- **Age key — single point of failure** — потеря private age key →
  потеря всех secrets. Mitigation: keys hosted на нескольких operator'ах
  + backup в физическом сейфе. Tested DR procedure — обязательное part
  Phase 2 deploy'а.
- **Нет fine-grained ACL** — кто имеет age private key, у того доступ ко
  всем secrets для этого environment'а. Mitigation: separate keys per
  env (dev / staging / prod).
- **SOPS требует учиться** — developer onboarding получает +1
  инструмент. Compensation: `make decrypt-dev` / `make encrypt-dev`
  обёртки скрывают command-line.

### Технические следствия

- Новый dir `deploy/secrets/` в repo:
  - `dev.enc.yaml`, `staging.enc.yaml`, `prod.enc.yaml`.
  - `.gitkeep` для пустого dir пока secrets не landed.
- Root `.sops.yaml` — creation rules (per-env age recipients).
- `.gitignore` updates: `*.env`, `*.env.*`, `!*.enc.yaml`.
- `infra/Makefile` (или backend's) — targets `decrypt-dev`,
  `encrypt-dev`, etc.
- `docker-compose.yml`: убрать hardcoded `${VAR:-default}` для secrets —
  они должны прийти из `.env.local` (через SOPS decrypt). Default'ы
  оставить только для НЕ-secret'ов (ports, URLs).
- CI: `Integration (Keycloak)` job не получает реальных secrets — он
  использует hardcoded dev-only credentials (это OK, integration env
  isolated).
- Documentation: README раздел «Local-dev setup» — пошагово как
  настроить age key + `sops decrypt`.

## Открытые вопросы (требуют Architect-решения отдельно)

1. **Где живут age private keys?**
   Вариант A: на ноутбуках operators + LastPass / 1Password backup.
   Вариант B: separate age private keys per CI-job / k8s-cluster через
   secret managers облака (тот же Yandex Lockbox для одного-единственного
   age key — приемлемо, поскольку это single bootstrap secret).
2. **Кто имеет prod age key** — на старте 1 человек (Architect), позже
   расширяется через age recipients (можно перешифровать без потерь).
3. **Rotation cadence** — рекомендуется ежеквартально для DB / Keycloak
   admin, immediately on personnel change.
4. **Backup-and-restore process** — отдельный runbook документ.

## Ссылки

- CLAUDE.md «Технологический стек», «ФЗ-152»
- ADR-0001 раздел 5 (ФЗ-152)
- SOPS: https://github.com/getsops/sops
- Age: https://github.com/FiloSottile/age
- Flux SOPS integration: https://fluxcd.io/flux/guides/mozilla-sops/
- Связанные ADR: ADR-0007 (Keycloak), ADR-0008 (DB)
- Backlog issues (зависят от этого ADR): #114 (Dockerfile — done w/o
  secrets), prod docker-compose (отдельный PR после approve), k8s
  manifests (отдельный PR).

# Runbook: SOPS secrets disaster recovery

Адресует ADR-0009 §"Открытые вопросы" + closes #118.

## Scope

Что считаем DR-событием:
- **Loss of one recipient** — один из operators потерял доступ к age private
  key (laptop сломался, 1Password locked out, etc.).
- **Loss of all recipients** — все age private keys для environment
  недоступны одновременно (catastrophic).
- **Compromised key** — есть основание подозревать что private key утёк.
  Treat как `loss of all recipients` для этого environment'а: rotate +
  re-issue underlying secrets.

## Custody policy (от ADR-0009)

| Env | Recipients (production target) | Backup |
|---|---|---|
| **Dev** | Каждый developer на laptop | 1Password vault `reHome / Dev secrets` (доступ — все developers) |
| **Staging** | DevOps + Architect | 1Password vault `reHome / Staging secrets` |
| **Prod** | Architect (1 recipient на старте) → +1 DevOps когда нанят | Sealed envelope в физическом сейфе (printed key + paper backup + age-keygen output) + 1Password vault Architect'а |

**Stage 1** (current): только prod recipient = Architect. Dev key shared
через 1Password.

**Stage 2** (когда нанимается второй person): `age-keygen` → add public part
в `.sops.yaml` recipients → `make rotate` → 1Password / sealed envelope
update.

## Rotation cadence

| Event | Action |
|---|---|
| Personnel change (anyone leaves team) | Immediate rotate per env где у них был доступ |
| Suspected leak / compromised laptop | Immediate rotate + re-issue underlying secrets |
| No incident | Quarterly (Q1/Q2/Q3/Q4) для prod; ad-hoc для dev |

## Procedures

### 1. Loss of one recipient (no leak)

Если utratitsy laptop / locked out 1Password но key НЕ утёк — у нас всё
ещё есть other recipients для этого environment'а.

```bash
# Operator (другой recipient'а) выполняет:
cd /path/to/repo

# 1. Generate new age key для пострадавшего operator'а:
age-keygen -o ~/new-recipient.age.key
NEW_PUB=$(age-keygen -y ~/new-recipient.age.key)

# 2. Замените lost recipient'а в .sops.yaml:
#    - откройте .sops.yaml
#    - найдите соответствующий env (dev/staging/prod)
#    - замените lost age:... recipient на $NEW_PUB
#    - commit

# 3. Re-encrypt все existing secrets под new recipient set:
make -C infra rotate

# 4. Передайте new private key пострадавшему operator'у out-of-band:
#    - 1Password share (1-time link с expiry) для dev/staging
#    - физический exchange + 1Password vault для prod
#    - НИКОГДА не через Slack / email / git
```

### 2. Loss of all recipients (catastrophic — no leak)

Если все private keys для env недоступны (все laptops умерли,
1Password vault locked out, физический сейф недоступен) — recovery
через physical backup.

```bash
# 1. Открыть sealed envelope из физического сейфа.
# 2. Восстановить age private key из printed copy:
nano ~/.config/sops/age/keys.txt  # вставить из printed (внимательно)

# 3. Verify:
make -C infra sops-check

# 4. Сразу rotate (старый key возможно был compromised — physical
#    access к сейфу = serious incident):
age-keygen -o ~/new-fresh.age.key
# ... повторить procedure 1.

# 5. После rotate — печать new sealed envelope, заменить в сейфе.
```

### 3. Compromised key (suspected leak)

Treat как catastrophic loss + immediate rotate of UNDERLYING secrets
(потому что compromise возможно произошло после кого-то successfully
расшифровал и записал actual passwords).

```bash
# 1. Rotate age recipients (procedure 1 или 2).

# 2. Rotate ALL secrets для затронутого env:
#    - postgres passwords (через ALTER USER ... PASSWORD)
#    - Keycloak admin password (через Admin Console)
#    - Keycloak m2m client secret (regenerate)
#    - Любые other secrets stored в .enc.yaml
#
#    Plain text new values временно в /tmp/new-secrets.yaml:
make -C infra encrypt-prod FILE=/tmp/new-secrets.yaml
rm /tmp/new-secrets.yaml

# 3. Redeploy services с new secrets.

# 4. Investigate как произошла compromise: audit logs, access patterns,
#    affected systems. Update threat model.

# 5. Notify stakeholders (Architect + любые регуляторы если ФЗ-152
#    incident; см. CLAUDE.md §"Безопасность и ФЗ-152").
```

## Annual DR test

Тестируем procedure ежегодно (минимум) для prod. Цель — убедиться что
documented procedure actually работает и procedures не deviated от
реальности.

```bash
# Schedule: каждый Q4 (Nov-Dec). 30 minutes max.

# 1. На отдельной тестовой машине, fresh checkout репо:
git clone git@github.com:rehome-one/rehome-kb-platform.git
cd rehome-kb-platform

# 2. Установить sops + age (вне cached ~/.config — pretend fresh laptop).

# 3. Загрузить prod age key из physical backup (sealed envelope из сейфа).

# 4. Verify `make -C infra decrypt-prod` succeeds и produces sensible output.

# 5. Cleanup: уничтожить test machine state (или просто разные
#    SOPS_AGE_KEY_FILE path), не оставлять prod key на test box.

# 6. Document в `docs/runbooks/dr-test-YYYY.md` дату + результат +
#    обнаруженные deviations.
```

## Failure modes мы НЕ покрываем

- **Catastrophic data center loss** (Postgres data gone) — это backup/restore
  procedure для DB, не SOPS DR. Отдельный runbook когда DB backups land.
- **Compromised laptop с unlocked SSH agent / git credentials** — отдельная
  incident response procedure (не SOPS-specific).
- **Insider threat** — operator с легитимным доступом deliberately leaks
  secrets. Mitigation: audit logging access (TODO: structured logs grep
  для `sops decrypt` invocations), separation of duties когда команда
  growth'нется.

## Контакты

- **Primary**: Architect (Evgeniy)
- **Secondary**: TBD когда нанимается DevOps
- **Эскалация incident'ов**: см. CLAUDE.md «Безопасность и ФЗ-152»

## Ссылки

- ADR-0009 (secrets management — primary source of truth)
- Issue #118 (open questions, closed by this runbook)
- `infra/Makefile` (operational targets: decrypt/encrypt/rotate)
- `deploy/secrets/README.md` (everyday usage)
- `.sops.yaml` (recipient configuration)

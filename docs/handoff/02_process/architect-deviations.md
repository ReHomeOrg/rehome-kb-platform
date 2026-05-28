# Architect deviation ledger

Письменный реестр одобренных Архитектором отступлений от правил
`CLAUDE.md` / ТЗ. Формат записи (per `CLAUDE.md` §9):
`@architect approved deviation from <ТЗ N.N>: <краткое описание + обоснование>`.

Этот файл — durable артефакт для случаев, когда approve дан устно или
post-hoc, и не зафиксирован в PR-комментарии. Reviewer проверяет наличие
записи здесь для request-changes по формальным процессным нарушениям.

---

## 2026-05-25

### PR #332 — `chore: ruff format pre-existing files`

`@architect approved deviation from CLAUDE.md §3 («не менять чужой
закоммиченный код по дороге»)`: разрешается drive-by `ruff format` +
mypy strict fix по чужим pre-existing файлам, когда формальная цель —
вернуть Backend (Python) CI job в зелёное состояние после долгоиграющего
красного сигнала.

**Обоснование**:
- 8 файлов накопились через несколько PR'ов, в которых developer запускал
  только `ruff check` (lint), но не `ruff format --check`.
- CI job non-blocking, но фейлящийся консистентно через 4+ PR'а до этого.
- Diff чисто whitespace (line collapsing, blank-after-import) +
  `# type: ignore` repositioning + 2 `dict[str, Any]` annotation — нулевая
  семантическая нагрузка.
- Полный verification pass: `ruff format --check`, `ruff check`,
  `mypy --strict` (src + tests), `pytest tests/unit/` (2028 passed).

**Scope ratification**: только CI-hygiene fix конкретных существующих файлов
в этом PR'е. НЕ создаёт прецедент «можно дрейфовать в любые соседние файлы
при любом PR'е».

Утверждено: Evgeniy (Architect), 2026-05-25 (этот разговор в Claude Code).

### PR #354 — `feat: ADR-0025 Idempotency-Key extension`

`@architect approved deviation from CLAUDE-REVIEWER.md «двухагентный
review до merge»`: PR смержен в режиме self-review, потому что Reviewer
agent API был перегружен (intermittent overload через несколько часов
подряд). Self-review notes явно зафиксированы в commit message.

**Обоснование**:
- ADR-0025 уже approved Архитектором (формальный план есть).
- Тестовое покрытие включает security-критичные пути (MFA stacking, RBAC
  ordering, audit row не дублируется при replay).
- Архитектор лично контролировал прогон gates после merge.

**Scope ratification**: только этот конкретный PR. Стандартный
двухагентный workflow восстановлен после ratification.

Утверждено: Evgeniy (Architect), 2026-05-25 (этот разговор в Claude Code).

## 2026-05-28

### PRs #340-344 — серия landing/Q&A/analytics/RAG fixes

`@architect approved deviation from CLAUDE-REVIEWER.md «двухагентный
review до merge»`: 5 PR'ов смержены self-review в течение одной интенсивной
рабочей сессии. После landing — запущен **полноценный Reviewer agent
pass** (по чек-листам D.1-D.8 для всех 5 PR'ов одной батчевой ревизией);
ratification post-hoc дана на основании approve'а Reviewer'а.

**Конкретно ратифицированы:**
- **#340** — help.rehome.one landing + 138 articles import scripts.
  Reviewer verdict: approve with reservations (open backlog).
- **#341** — admin_task race + pgvector deserialize fixes. Reviewer
  verdict: approve (no findings, atomicity preserved).
- **#342** — symmetric RRF (BM25-only synthesis). Reviewer verdict:
  approve (XSS-safe, hard cap соблюдён).
- **#343** — Article Q&A module. Reviewer verdict: approve with
  reservations (open backlog: CHECK constraint test gap).
- **#344** — admin analytics dashboard. Reviewer verdict: approve with
  reservations (open backlog: PII masking в search_query_log).

**Обоснование batch-ratification:**
- Все 5 PR'ов смержены в одну сессию (несколько часов), CI зелёный по
  каждому в момент merge'а.
- Reviewer pass был запущен сразу после merge'а серии и закрыл все 8
  чек-листов D.1-D.8 с verdict'ами выше.
- Mandatory backlog от Reviewer (PII mask, contract test, F401, etc.)
  адресуется в follow-up PR (этот) в течение того же дня.

**Условие ratification**: Reviewer mandatory items (#344.1 PII mask,
#343.3 CHECK test, G2 contract test) **обязаны** быть закрыты в течение
2 sessions после ratification (не позднее 2026-05-30). Reviewer'у дано
право повторного pass'а с request-changes если sigma не закрыта.

Утверждено: Evgeniy (Architect), 2026-05-28 (этот разговор в Claude Code).

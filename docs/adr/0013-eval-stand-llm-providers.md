# ADR-0013: Eval-стенд для LLM-провайдеров

## Статус

[ ] Предложено
[x] Принято
[ ] Заменено ADR-MMMM
[ ] Отклонено

- **Дата:** 2026-05-16
- **Автор:** Агент-Разработчик
- **Согласовано Архитектором:** да, 2026-05-16 (чат-сессия, scope + 3 решения)

## Контекст

ТЗ §3 «Чат-поиск» (`docs/handoff/01_postanovka/02_Чат-поиск_ТЗ.md`)
определяет eval-стенд как отдельный сервис, прогоняющий фиксированный
набор тестовых вопросов через все подключённые LLM-провайдеры и
считающий метрики качества и стоимости. ТЗ §3.5: финальный выбор
провайдера формализуется через composite score:

    composite = answer_correctness × 0.4
              + faithfulness × 0.3
              + citation_accuracy × 0.2
              + refusal_correctness × 0.1

Backend сейчас имеет:

- `LLMProvider` абстракция (`src/api/chat/llm/base.py`) с реализациями
  `MockProvider` (детерминистский) и `VLLMProvider` (production-ready).
- RAG retrieval (BM25 + pgvector через RRF) — `src/api/search/`.
- Chat router с SSE streaming.

Открытые вопросы перед стартом:

- Где живёт код — отдельный сервис `kb-eval` или модуль внутри `kb-api`?
- LLM-judge — какая модель и кто её хостит?
- Bootstrap dataset — кто и в каком формате готовит 200 размеченных пар?
- Composite score формула — все 4 метрики сразу или MVP с placeholders?

## Решение

### 1. Размещение — модуль `backend/src/eval/` внутри `kb-api` repo

**Не** отдельный сервис на старте. Причины:

- Eval использует те же `LLMProvider` adapters и RAG retrieval — нет смысла дублировать через RPC.
- Запуск через CLI (`python -m src.eval.cli`) — не runtime-критично, не требует своего deploy'я.
- Если позже понадобится UI/dashboard / cron на отдельном поде — рефактор в отдельный сервис прямолинейный, абстракции уже в `src/eval/`.

Структура модуля:

    backend/src/eval/
    ├── __init__.py
    ├── dataset.py     # JSONL loader + Pydantic schema EvalPair
    ├── runner.py      # async harness — запускает provider на dataset
    ├── metrics.py     # latency, cost, citation_overlap + composite formula
    ├── judge.py       # Judge ABC + MockJudge (LLMJudge — backlog)
    ├── report.py      # JSON output writer
    └── cli.py         # argparse entrypoint

### 2. Bootstrap dataset format — JSONL

Одна пара на строку, Pydantic schema:

    {
      "id": "faq-deposit-001",
      "category": "simple_faq",
      "scope": "public_anonymous",
      "question": "Сколько составляет залог?",
      "expected_answer": "Залога нет. Есть сервисный платёж...",
      "expected_citations": ["article:rental-service-fee-policy"],
      "tags": ["finance", "onboarding"]
    }

Категории — фиксированный enum по ТЗ §3.1:
`simple_faq | legal | financial | multi_step | paraphrase | dialog_context | off_topic | prompt_injection | pii_third_party`.

В MVP — 10 sample пар в `tests/eval/golden.jsonl` (placeholder, реальные 200 пар — задача content team).

### 3. Composite score — формула с placeholders в MVP

ТЗ §3.5 формула содержит 4 метрики. В MVP без LLMJudge мы можем считать только `citation_accuracy` (детерминистически через intersection с expected_citations). Остальные 3 заполняются `None` в report, composite остаётся `None` пока не все доступны.

Это намеренно: лучше явный `None` чем фейковый "compute everything as 1.0".

    @dataclass
    class EvalScores:
        answer_correctness: float | None  # LLMJudge — backlog
        faithfulness: float | None        # LLMJudge — backlog
        citation_accuracy: float | None   # MVP: deterministic
        refusal_correctness: float | None # LLMJudge — backlog

    def composite_score(s: EvalScores) -> float | None:
        if any(v is None for v in (s.answer_correctness, s.faithfulness,
                                   s.citation_accuracy, s.refusal_correctness)):
            return None
        return (s.answer_correctness * 0.4
                + s.faithfulness * 0.3
                + s.citation_accuracy * 0.2
                + s.refusal_correctness * 0.1)

### 4. LLM-judge — отложено до второго провайдера

ТЗ §3.3 рекомендует GPT-4 / Claude Sonnet / YandexGPT Pro как judge.
- GPT-4 / Claude — out-of-РФ, нарушают ФЗ-152.
- YandexGPT Pro — РФ-located, но интеграция-провайдер ещё не реализована (`LLMProvider` есть только vLLM).
- Использовать тот же vLLM как judge → bias (модель оценивает сама себя).

Решение: в этом эпике делаем только `MockJudge` (детерминистский — для unit-тестов pipeline'а). `LLMJudge` фабрика существует, но `NotImplementedError` пока не подключён второй провайдер. Когда landит'ся `YandexGPTProvider` или `GigaChatProvider` — отдельный PR с `LLMJudge` implementation + valid'ация на 50 ручных пар (ТЗ §3.3).

### 5. Метрики MVP (точное)

| Метрика | Источник | Computed |
|---------|----------|----------|
| `latency_seconds` | wall-clock между `runner.start` и `provider.generate.done` | ✅ MVP |
| `prompt_tokens` / `completion_tokens` | `LLMProvider.count_tokens()` | ✅ MVP |
| `cost_rub` | tokens × provider rate (из `LLMProvider.cost_per_1m_*`) | ✅ MVP |
| `citation_accuracy` | `len(actual ∩ expected) / len(expected)` | ✅ MVP |
| `answer_correctness` | LLMJudge | ❌ backlog |
| `faithfulness` | LLMJudge | ❌ backlog |
| `refusal_correctness` | LLMJudge (для категорий off_topic/pii/injection) | ❌ backlog |
| `tone_consistency` | Manual + LLMJudge | ❌ backlog (manual выборки 10% per run) |

### 6. Output — JSON report, версионированный

    {
      "run_id": "uuid",
      "run_started_at": "2026-05-16T12:00:00Z",
      "provider": "mock",
      "judge": "mock",
      "dataset_path": "tests/eval/golden.jsonl",
      "dataset_sha256": "...",
      "per_pair": [
        {"id": "faq-deposit-001", "latency_seconds": 0.42,
         "prompt_tokens": 150, "completion_tokens": 50, "cost_rub": 0.003,
         "actual_answer": "...", "actual_citations": [...],
         "scores": {"citation_accuracy": 1.0, "answer_correctness": null, ...},
         "composite": null}
      ],
      "aggregate": {
        "latency_p50": 0.4, "latency_p95": 0.8,
        "cost_per_query_avg": 0.003,
        "citation_accuracy_avg": 0.85,
        "composite_avg": null
      }
    }

Reports не commit'ятся (gitignore `reports/`) — каждый run даёт новый файл, decision'ы — в commit'е с обоснованием + ссылкой на report file.

### 7. Test strategy

- Unit tests на dataset loader (валидация, malformed JSONL, неизвестная категория).
- Unit tests на metrics — детерминистические для citation_accuracy, mocked для time.
- Integration test: full pipeline с `MockProvider` + `MockJudge` + 3-pair sample dataset → assert JSON report shape.
- НЕТ интеграции с реальным провайдером в CI — это smoke-тест следующего PR'а (когда LLMJudge land'ит'ся).

## Альтернативы

### A. Отдельный сервис `kb-eval` сразу

Pro: чистая граница, может deploy'ить independently.
Con: дублирование `LLMProvider` adapters, дополнительный CI job, оверхед для P0.5 фичи без production-критичности.
Отвергнуто — модуль `src/eval/` обеспечивает изоляцию без overhead'а.

### B. Все 4 метрики сразу через LLMJudge с vLLM

Pro: single эпик, не оставляем "TODO".
Con: bias (модель сама себя оценивает), нет валидации judge'а против human labels.
Отвергнуто — лучше явные `None` чем сомнительные scores.

### C. CSV вместо JSONL

Pro: контент-команде проще редактировать в Excel.
Con: hard на escape'ить кавычки/переносы в expected_answer, потеря nested структуры (citations array).
Отвергнуто — JSONL стандарт для labeled datasets в ML world; конвертер CSV→JSONL — отдельный tooling если нужно.

## Последствия

### Позитивные

- Pipeline готов до того, как content team разметит 200 пар — можно прогонять на 10 sample'ах и проверять что harness работает.
- LLMProvider abstraction уже есть → adding YandexGPT не сломает eval.
- ADR-0003 storage-level access_level соблюдён — eval не bypass'ит проверки прав.

### Негативные / риски

- В MVP composite_score всегда `None` — не даёт автоматического выбора провайдера. Нужно ждать LLMJudge (P1 эпик).
- 10 sample пар недостаточно для статистической значимости. Decision'ы по провайдеру требуют 200 пар.
- Reports не commit'ятся → отсутствует git-tracked history. Аналитика "как metrics менялись неделю" требует или внешнего storage, или отдельной таблицы в Postgres. Backlog.

## Backlog (явно отложено)

1. `LLMJudge` implementation после landing'а YandexGPT/GigaChat провайдера.
2. Human validation: 50 пар разметить вручную, сравнить с judge — должно совпадать ≥80% (ТЗ §3.3).
3. CI smoke run (10 ключевых вопросов на каждом commit'е, ТЗ §3.4).
4. A/B механизм — 5% реального трафика на альтернативу.
5. Cost-quality Pareto-граница visualization (matplotlib script).
6. Postgres table для report metadata + indexed search.
7. Web UI / dashboard для просмотра runs (после Phase 2 chat).

## Ссылки

- ТЗ §3 «Eval-стенд» — `docs/handoff/01_postanovka/02_Чат-поиск_ТЗ.md`
- ADR-0001 — Stack outline (Category A: kb-eval как свой код)
- ADR-0003 — Storage-level access_level enforcement
- ADR-0010 — RAG kb-search (источник retrieval'а для eval)

# ADR-0028: Публичный анонимный чат-виджет → канонический KB-backend; эскалация как крайняя мера; цитаты отдельным блоком

## Статус

[ ] Предложено
[x] **Принято**
[ ] Заменено ADR-MMMM
[ ] Отклонено

- **Дата:** 2026-07-11
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** **да**, 2026-07-11
- **Approve note:** Architect выбрал вариант A (перенаправить виджет на 93.x + анон)
  vs B (сделать per-stack backend «реальным»); одобрил `CHAT_REQUIRE_AUTH=false`,
  merge PR #381/#382 и деплой на 93.x. Подтверждено в Claude Code session 2026-07-11.

## Контекст

Продовая топология KB — **два деплоя** (см. [[state-of-code]] §CS.15):

- **`help.rehome.one` → 93.77.180.57 (Yandex Cloud)** — канонический KB-backend
  (`rehome-kb-platform-api`, образ `:local`), БД `rehome_kb` c KB v7.3 (296 статей),
  YandexGPT + hf-эмбеддинги. Здесь работает `/help`-чат.
- **`rehome.one` → 95.213.154.92 (Selectel)** — главный сайт (`rehome-frontend-prod`,
  Next.js) + отдельный `rehome-kb-frontend-prod` для `/help`. Оба **проксируют**
  на 93.x — своего «настоящего» KB-backend у 95.x нет.

На главной rehome.one есть **анонимный виджет «Ассистент поддержки»** (`SupportWidget`,
`rehome-frontend-next/src/widgets/SupportWidget`). Он зовёт `/api/kb/chat/sessions`,
который главный фронт проксирует на `KB_BACKEND_INTERNAL_URL`. Исторически эта
переменная указывала на **per-stack локальный backend** `rehome-kb-backend-<STACK>`
(compose-дефолт `http://rehome-kb-backend-${STACK_NAME}:8000`), который на 95.x был
**vestigial**: `LLM_PROVIDER=mock`, `EMBEDDING_PROVIDER=mock`, старая БД на 164 статьи.

Симптомы (июль 2026), которые выявили проблему:
1. Виджет отдавал **mock-ответы** («Нашёл для вас полезные статьи» + нерелевантные
   статьи из старой БД) — потому что ходил на mock-backend, а не на 93.x.
2. `KB_BACKEND_BASE_URL`/`KB_FRONTEND_TAG` задавались ad-hoc и **затирались деплоем**
   (`/opt/rehome/prod/.env` регенерится из GH-секрета `ENV_FILE_PROD`), из-за чего фронт
   после деплоя откатывался на mock-дефолт.
3. `93.x`-backend требовал авторизацию для чата (`CHAT_REQUIRE_AUTH=true`, secure default,
   энфорс из PR #379), а виджет — **анонимный** → 401.
4. Эскалация «обратитесь к оператору» дописывалась почти в каждый ответ; в тексте ответа
   были технические сноски источников `[N]`.

Требования: единый источник истины KB-данных (v7.3) и LLM (YandexGPT), «оператор —
крайняя мера, решать максимум силами ИИ», человечные ответы без техшума. ФЗ-152:
данные и LLM в РФ (Yandex Cloud) — не нарушается.

## Решение

1. **Виджет и весь KB-контент главного сайта ходят на канонический backend (93.x).**
   Compose-дефолт на 95.x изменён: `KB_BACKEND_INTERNAL_URL` (главный фронт) и
   `BACKEND_BASE_URL` (kb-frontend) по умолчанию = `https://help.rehome.one/api/platform`.
   Дефолт зашит в hand-maintained `/app/docker-compose.yml` (деплой его не регенерит,
   в отличие от `.env`), поэтому переживает деплой. Теги образов запиннены
   (`KB_FRONTEND_TAG`, `KB_BACKEND_TAG`) в том же дефолте — на случай недоступности
   Selectel-registry.
2. **Анонимный чат на 93.x включён:** `CHAT_REQUIRE_AUTH=false` в `.env.kb-platform`.
   Это **амендит** backend-энфорс из PR #379: auth-гейт `/help`-чата теперь держится
   на **frontend-редиректе** (`app/chat/layout.tsx` редиректит анона в `/login`), а не
   на backend. Анон-flow (`X-Chat-Session-Token`) — штатный путь виджета.
3. **Per-stack mock-backend (`rehome-kb-backend`) декоммишен как backend виджета** —
   на него больше ничто не маршрутизируется. Контейнеры на 95.x остановлены; тома
   сохранены (обратимость).
4. **Эскалация к оператору = крайняя мера.** Реализовано двумя слоями:
   - **Overlay-промпт** (`chat.system_prompt`, ADR-0019): эскалация только при явных
     триггерах (нет ответа в базе / нужен человек / конфликт-юрспор / явный запрос),
     без дежурной приписки; человечный тон, прямой ответ «кто платит».
   - **Confidence-gate в коде** (PR #381 / Issue #383): `has_usable_context()` +
     `apply_no_context_rule()` — no-context директива дописывается в system prompt
     ТОЛЬКО когда retrieval пуст/слабый (`RAG_MIN_CONFIDENCE_SCORE`, default 0 = по
     пустому retrieval).
5. **Цитаты — отдельным блоком, не в тексте.** `build_rag_system_prompt` запрещает
   inline-`[N]`; `strip_citation_markers()` срезает остаточные маркеры в JSON и persist
   SSE (PR #382 / Issue #384). Источники пользователь видит блоком `citations` (карточки).

## Альтернативы

1. **Сделать per-stack backend «настоящим»** (LLM=yandex_gpt + креды, EMBEDDING=hf,
   засидить v7.3 в `rehome-postgres-kb-prod`, анон) — отклонена: дублирование
   инфраструктуры и данных, оверхед сидинга, риск дрейфа двух копий KB, лишние
   ресурсы; registry на тот момент лежал (Selectel-работы).
2. **Держать эскалацию только промптом** (без code-гейта) — отклонена: малая LLM
   (yandexgpt-lite) нестабильно слушается негативной инструкции, эскалация оставалась
   бы недетерминированной; нужен data-driven сигнал по retrieval.
3. **Рендерить `[N]` как кликабельные ссылки во виджете** — отклонена: виджет — лёгкий
   embed на главном сайте, полноценный citations-UI там избыточен; источники уже
   отдаются отдельным блоком.
4. **Оставить backend-энфорс `CHAT_REQUIRE_AUTH=true` и дать виджету логиниться** —
   отклонена: виджет на главной для всех посетителей анонимный по продуктовому дизайну;
   принуждать к логину до вопроса в чат — потеря конверсии.

## Последствия

### Положительные

- Единый источник истины: и `/help`-чат, и виджет на главной, и KB-контент главного
  сайта идут на 93.x (v7.3 + YandexGPT + hf) — нет второй mock-копии и дрейфа.
- Виджет отвечает по-настоящему, человечно, без техсноскок и навязчивого «оператора».
- Дефолты durable (в hand-maintained compose) — деплой не откатывает маршрут в mock.
- Эскалация редкая и data-driven; оператор — действительно крайняя мера.

### Отрицательные / компромиссы

- **Backend больше не энфорсит auth для чата** (`CHAT_REQUIRE_AUTH=false`). Auth-гейт
  `/help`-чата теперь только на frontend-слое (UI-редирект). Это ослабление
  security-posture относительно PR #379 — принято осознанно ради анон-виджета. Риск:
  прямой анонимный доступ к chat-API 93.x в обход UI.
- **Кросс-серверный вызов** 95.x→93.x по интернету на каждый запрос виджета/контента
  (латентность + зависимость от доступности help.rehome.one).
- **Стоимость:** анонимные обращения к YandexGPT биллятся (публичный виджет).
- Малая LLM: подавление техсносок/эскалации промптом не 100% — подстраховано
  детерминированным `strip_citation_markers` (для `[N]`); для тона остаётся вероятностный
  характер.

### Технические следствия

- 95.x `/app/docker-compose.yml`: дефолты `KB_BACKEND_INTERNAL_URL`/`BACKEND_BASE_URL`
  → 93.x; пины `KB_FRONTEND_TAG`/`KB_BACKEND_TAG`. Правки в hand-maintained файле
  (не через `.env`-регенерацию).
- 93.x `.env.kb-platform`: `CHAT_REQUIRE_AUTH=false`; рекапл `rehome-kb-platform-api`.
- Код: `system_prompt.py` (`has_usable_context`, `apply_no_context_rule`,
  `NO_CONTEXT_DIRECTIVE`, `strip_citation_markers`, запрет `[N]` в RAG-блоке),
  `router.py` (гейт + стрип), `config.py` (`RAG_MIN_CONFIDENCE_SCORE`). Миграций нет.
- Overlay `chat.system_prompt` в `system_config` (93.x) — тон/эскалация без деплоя.
- Хвост: рассмотреть перенос backend-энфорса auth в форму, различающую анон-виджет и
  `/help`-чат (напр. per-client policy), чтобы вернуть backend-гейт для `/help`.

## Ссылки

- ТЗ: Чат-поиск §5.1 (RAG «нет ответа»); принцип «оператор — крайняя мера».
- Связанные ADR: ADR-0010 (RAG stack), ADR-0019 (runtime config overlay `chat.system_prompt`).
- Амендит: backend chat auth-gate из PR #379 (`CHAT_REQUIRE_AUTH` secure default).
- PR/Issue: #381 (Issue #383, confidence-gated эскалация), #382 (Issue #384, стрип `[N]`).
- Внешние: OpenAI function-calling best practices (сверка агентной архитектуры;
  Tier 3 — function-calling / маршрут через kb-concierge — вынесен в отдельное обсуждение).

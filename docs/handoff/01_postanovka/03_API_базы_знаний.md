**Knowledge Base API**

Техническое задание и публичный контракт

*Подключение модуля базы знаний к платформе rehome.one*

ООО «РЕХОМ» · Версия 1.3 · Май 2026


> **ℹ️ Назначение документа**
>
> Документ описывает публичный API модуля базы знаний reHome, через который платформа rehome.one (и другие потребители) получают доступ к контенту, поиску и AI-чату. Документ задаёт контракт между двумя системами и должен поддерживаться в актуальном состоянии: любое breaking change требует версионирования и согласования с потребителями API. К документу прилагается машиночитаемая OpenAPI 3.1 спецификация (Приложение A), которая используется для генерации серверного кода, клиентов, mock-сервера и автотестов контрактов.


> **ℹ️ Что нового в версии 1.3**
>
> Финализированы UX-решения по коллаборантам (см. ПЗ «База знаний v1.4», раздел 10.8). Добавлены 2 новых эндпоинта в группу Collaborators: • POST /api/v1/collaborators/onboarding — публичная форма самостоятельной заявки коллаборанта, без авторизации. Реализует политику «коллаборант сам выбирает уровень кабинета». • PUT /api/v1/collaborators/{id}/portal-access — смена уровня кабинета (NONE/LIGHT/FULL). Понижение в любой момент, повышение — после первой успешной операции или одобрения оператором. Схема Collaborator расширена полями portal_access_history (история смен) и onboarding_source (как коллаборант появился в системе). Список webhook events дополнен collaborator.portal_access.changed и collaborator.onboarding.submitted. Итого 53 эндпоинта в v1.0.


**Оглавление**

*Оглавление сгенерируется автоматически.*

## 1. Введение

### 1.1. Контекст

База знаний reHome — отдельный модуль платформы с собственным набором микросервисов (kb-wiki, kb-help, kb-files, kb-vault, kb-staff, kb-hr, kb-search). Этот модуль должен предоставлять стабильный публичный API, через который другие части платформы используют его функции:

- Сайт rehome.one (Next.js): рендерит help-центр, встраивает чат-виджет, показывает страницы политик и оферты

- Личный кабинет (rehome.one/account): встраивает помощника, показывает контекстные подсказки, отдаёт пользовательские документы

- Админка /staff: внутренний чат для сотрудников, реестр документов, регламенты

- Мобильные приложения: в перспективе — тот же API

- Внешние потребители в перспективе: партнёры, исследовательские запросы

### 1.2. Цели API

1.  Развязка: rehome.one и kb-модуль развиваются независимо, не лезут в чужие базы данных.

2.  Стабильность: контракт версионируется, поломка обратной совместимости — событие со специальной процедурой.

3.  Безопасность: единая точка контроля access_level, идентификации, лимитов.

4.  Производительность: кеширование на уровне API, не на уровне rehome.one.

5.  Прозрачность: всё, что доступно через API, документировано в OpenAPI. Скрытых эндпоинтов нет.

### 1.3. Принципы дизайна

- **REST + OpenAPI 3.1:** стандарт индустрии, не требует специальных клиентов, отлично документируется, инструментарий зрелый.

- **Один контракт — два пути доступа:** тот же API доступен как server-to-server (мощная аутентификация, без user-context) и как browser-to-server (session/JWT, с user-context). Различие — в аутентификации и в правилах применения access_level.

- **Версионирование через URL prefix:** /api/v1/, /api/v2/ — крупные breaking changes. Мелкие совместимые изменения — без смены версии, с пометкой в changelog.

- **Ресурсо-ориентированный дизайн:** articles, documents, premises-cards, chat — каждый ресурс имеет CRUD-семантику или явную RPC-операцию (для чата).

- **Идемпотентность операций записи:** PUT/PATCH идемпотентны. POST с Idempotency-Key для критических действий (отправка сообщения в чат).

- **Cursor-based пагинация:** не offset-limit (плохо работает на больших объёмах и при изменениях во время пагинации).

- **Стриминг для чата:** Server-Sent Events (SSE) для длинных ответов LLM.

- **ETag и If-None-Match:** для GET статичного контента — поддержка кеширования на уровне HTTP.

### 1.4. Карта потребителей API

Гибридная модель доступа (server-to-server + browser-to-server) обусловлена реальным составом потребителей. Ниже — матрица всех известных и планируемых потребителей kb-API с указанием канала доступа, scope и приоритета.

#### 1.4.1. Текущие потребители (запуск MVP)

| **Потребитель**                              | **Канал**        | **scope**     | **Что использует**                                                |
|----------------------------------------------|------------------|---------------|-------------------------------------------------------------------|
| Сайт rehome.one — Next.js SSR (бэкенд)       | m2m (Bearer JWT) | kb:read (m2m) | GET /articles, /documents, /search для SEO-рендеринга help-центра |
| Сайт rehome.one — браузер (главная, каталог) | Anonymous        | guest         | GET /articles (public), POST /chat (как гость)                    |
| Личный кабинет арендатора                    | Cookie JWT       | tenant        | Чат с контекстом, свои документы, контекстные подсказки           |
| Личный кабинет собственника                  | Cookie JWT       | landlord      | Чат, свои карточки квартир, финансовый блок, документы            |
| Личный кабинет агента                        | Cookie JWT       | agent         | Карточки закреплённых объектов, регламенты                        |
| Админка /staff — поддержка                   | Cookie JWT       | staff_support | Внутренний чат со скриптами, поиск регламентов, карточки клиентов |
| Админка /staff — юристы                      | Cookie JWT       | staff_legal   | Документы все категорий, регламенты, аудит                        |
| Админка /staff — HR                          | Cookie JWT       | staff_hr      | Кадровые регламенты, личные дела, ЛНА                             |
| Админка /staff — администратор               | Cookie JWT + MFA | staff_admin   | Управление сотрудниками, аудит, настройки, переключение LLM       |

#### 1.4.2. Потребители 2-й волны (Phase 2-3)

| **Потребитель**                    | **Канал**                  | **scope**                   | **Что использует**                                |
|------------------------------------|----------------------------|-----------------------------|---------------------------------------------------|
| Telegram-бот для сотрудников       | m2m + user-mapping         | staff\_\*                   | Внутренний чат через Telegram, lookup-инструменты |
| Мобильное приложение iOS / Android | Bearer JWT (мобильный SDK) | tenant / landlord / agent   | Тот же API, что в браузере                        |
| Системы внутренней автоматизации   | m2m                        | kb:read + специфичный scope | Скрипты, регулярные отчёты, синхронизации         |

#### 1.4.3. Внешние потребители (после стабилизации)

| **Потребитель**                       | **Канал**                | **scope**                                          | **Что использует**                                                                    |
|---------------------------------------|--------------------------|----------------------------------------------------|---------------------------------------------------------------------------------------|
| Партнёры — клининг / переезд / ремонт | m2m с ограниченным scope | kb:partner:read (только публичные данные объектов) | Получение событий через webhooks, чтение карточек объектов в рамках выполняемых услуг |
| Страховая компания                    | m2m с ограниченным scope | kb:partner:read + insurance:write                  | Webhooks о событиях договоров, чтение страховых полисов                               |
| Контур.Диадок (ЭДО)                   | m2m                      | kb:documents:write                                 | Запись подписанных документов, статусы подписания                                     |
| Аналитика / агрегаторы                | m2m read-only            | kb:public:read                                     | Только публичные статьи и каталог документов                                          |


> **🔧 Принципиальные следствия для дизайна API**
>
> (1) Контракт один, но аутентификация разная — это требует двух securitySchemes (BearerAuth + CookieAuth) и явной декларации, что доступно без авторизации. (2) Часть эндпоинтов (POST /chat/sessions, GET /articles по PUBLIC) доступны без токена — для гостей сайта. (3) Партнёрский scope (kb:partner:*) выделяется в отдельную ветку для жёсткой изоляции — партнёр не должен иметь возможность получить даже минимальные внутренние данные. (4) Mobile приложения используют тот же контракт, что и web — это требует токенного, а не cookie-based варианта аутентификации, чтобы работало в native-приложениях.


### 1.5. Что НЕ входит в API

Явное перечисление того, что НЕ предоставляется через этот API — чтобы избежать неправильных ожиданий потребителей:

- Управление пользователями платформы rehome.one (конечные арендаторы, собственники, агенты) — это в зоне ответственности kb-auth / основной системы rehome.one. В kb-API только эндпоинты управления СОТРУДНИКАМИ kb-модуля (раздел 3.9.1).

- Платежи и финансы пользователей — обработка оплат через банк-партнёра и платёжный контур rehome.one. KB-API только показывает финансовый блок карточки квартиры (read), но не инициирует платежи.

- Каталог квартир и бронирования (продуктовая часть rehome.one). KB-API содержит только расширенные карточки уже опубликованных квартир.

- Прямой доступ к секретам менеджера паролей — kb-vault имеет собственный отдельный защищённый интерфейс с MFA, не через общий API.

- Кадровый портал в части расчёта зарплаты — 1С:ЗУП имеет собственный API. KB-API только хранит кадровые регламенты и личные дела как документы.

- Управление инфраструктурой (серверы, БД, сети) — это DevOps-инструменты, не публичный API.

## 2. Архитектура API

### 2.1. Общая схема

┌──────────────────────────────────────────────────────────────────┐  
│ Потребители (Consumers) │  
├──────────────────────────────────────────────────────────────────┤  
│ rehome.one │ /account │ /staff │ Мобильное │  
│ (Next.js SSR) │ (Next.js) │ (React) │ приложение │  
└────────┬────────┴────────┬───────┴──────┬───────┴────────┬───────┘  
│ │ │ │  
│ server-to- │ browser-to- │ browser-to- │  
│ server │ server │ server │  
│ (m2m token) │ (JWT cookie) │ (JWT cookie) │  
│ │ │ │  
▼ ▼ ▼ ▼  
┌──────────────────────────────────────────────────────────────────┐  
│ API Gateway (FastAPI) │  
│ • Authentication (m2m JWT / user JWT) │  
│ • Rate limiting │  
│ • Request logging │  
│ • CORS / CSP │  
│ • OpenAPI swagger UI │  
└────────┬─────────────────────────────────────────────────────────┘  
│  
├──────────────────┬─────────────────┬──────────────────┐  
▼ ▼ ▼ ▼  
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  
│ kb-wiki │ │ kb-files │ │ kb-search │ │ kb-staff │  
│ (статьи, │ │ (документы, │ │ (RAG-чат, │ │ (карточки │  
│ FAQ) │ │ подписи) │ │ поиск) │ │ квартир) │  
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘

### 2.2. Два режима аутентификации

#### 2.2.1. Машина-к-машине (m2m)

Используется когда сервер rehome.one от своего имени запрашивает данные у kb-API (например, SSR-рендеринг help-центра, фоновые задачи синхронизации).

- Метод: OAuth 2.0 Client Credentials Grant

- Заголовок: Authorization: Bearer \<m2m_jwt\>

- Токен выдаётся через kb-auth (Keycloak), client_id = «rehome-platform», секрет — в менеджере паролей

- Время жизни токена: 1 час, авто-обновление перед истечением

- Scopes доступа определяются клиентом: kb:read, kb:write:articles, kb:write:premises и т.д.

- Все m2m-запросы тарифицируются отдельным rate limit (выше, чем browser)

**Пример заголовка:**

POST /api/v1/articles/search  
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...  
X-Client-Id: rehome-platform  
X-Request-Id: 7b3a8f1e-...  
Content-Type: application/json

#### 2.2.2. Пользователь-через-браузер (user)

Используется когда конечный пользователь (наниматель, собственник, сотрудник) делает действие через UI.

- Метод: JWT, хранится в HttpOnly Secure Cookie с SameSite=Lax

- Заголовок: Cookie: kb_session=eyJ... (автоматически отправляется браузером)

- Токен выдаётся через kb-auth при логине пользователя в основной системе rehome.one

- Время жизни: 24 часа, бесшовный refresh через refresh_token (HttpOnly Cookie)

- CSRF-защита: double-submit cookie + проверка X-CSRF-Token заголовка на mutating запросах

- scope (роль) пользователя зашит в JWT: claim role ∈ {guest, tenant, landlord, agent, staff_support, staff_legal, staff_admin}

- Rate limit персональный, привязан к user_id из токена

#### 2.2.3. Гость (без аутентификации)

Публичные эндпоинты (read-only статьи help-центра, публичные документы) доступны без токена. Помечаются в OpenAPI флагом security: \[\].

### 2.3. Контроль доступа — access_level и scope

Каждый ресурс в kb имеет атрибут access_level. Каждый запрос имеет вычисленный scope (на основе аутентификации). Фильтрация применяется на уровне хранилища (Qdrant payload filter, Postgres WHERE), не на уровне приложения.

| **scope (вычисляется бэкендом)** | **Какие access_level доступны**                             |
|----------------------------------|-------------------------------------------------------------|
| guest                            | PUBLIC                                                      |
| tenant                           | PUBLIC + LOGGED + свои данные                               |
| landlord                         | PUBLIC + LOGGED + свои данные (включая свои premises_cards) |
| agent                            | PUBLIC + LOGGED + AGENT (для закреплённых объектов)         |
| staff_support                    | PUBLIC + LOGGED + STAFF                                     |
| staff_legal                      | PUBLIC + LOGGED + STAFF + LEGAL                             |
| staff_admin                      | Все уровни, кроме HR_RESTRICTED                             |
| staff_hr                         | PUBLIC + LOGGED + STAFF + HR_RESTRICTED                     |
| m2m (rehome-platform)            | По заявленному scope в токене                               |


> **📌 Критический инвариант**
>
> scope НИКОГДА не передаётся клиентом. Только бэкенд вычисляет его из проверенного токена. Любая попытка передать scope в payload запроса игнорируется. Это техническая защита от подделки прав — без неё одна ошибка фронтенда становится утечкой ПДн.


### 2.4. Базовые URL и среды

| **Среда**   | **Базовый URL**                   | **Назначение**                            |
|-------------|-----------------------------------|-------------------------------------------|
| Production  | https://api.rehome.one/kb         | Боевая среда                              |
| Staging     | https://api.staging.rehome.one/kb | Предпрод, идентичный production           |
| Development | https://api.dev.rehome.one/kb     | Разработка                                |
| Local       | http://localhost:8000/kb          | Локальная разработка через docker-compose |

### 2.5. Версионирование

- Версия в URL: /api/v1/, /api/v2/. Текущая — v1.

- Минорные совместимые изменения (добавление новых полей в ответ, новых необязательных параметров, новых endpoint'ов) — без смены версии.

- Breaking changes (удаление полей, изменение их типа, обязательные новые параметры) — только новая мажорная версия.

- Старая версия поддерживается минимум 6 месяцев после выхода новой. Уведомление о deprecation — за 3 месяца через заголовок Deprecation и в changelog.

- Заголовок X-API-Version в каждом ответе содержит точную semver-версию backend'а (например, 1.4.2).

### 2.6. Обратные вызовы (webhooks)

Для событий, инициируемых внутри kb-модуля, но интересных платформе rehome.one (например, «статья опубликована», «документ подписан»), используются webhooks.

- rehome.one регистрирует callback URL через POST /api/v1/webhooks

- kb отправляет HTTP POST на этот URL при наступлении событий

- Подпись: заголовок X-Webhook-Signature = HMAC-SHA256(secret, body)

- Retry: 5 попыток с exponential backoff (1s, 5s, 30s, 5min, 30min)

- Idempotency: каждое событие имеет уникальный event_id, потребитель должен дедуплицировать

Перечень событий — в разделе 5.

## 3. Endpoints — каталог

Группировка по ресурсам. Полная техническая спецификация — в Приложении A (OpenAPI YAML). Здесь — обзорный каталог с назначением каждого endpoint'а.

### 3.1. Health и meta

**GET /api/v1/health**

Liveness probe. Возвращает 200 OK всегда, если процесс работает.

**GET /api/v1/ready**

Readiness probe. Возвращает 200 OK если все зависимости (Postgres, Qdrant, MinIO) доступны. Иначе 503.

**GET /api/v1/version**

Версия API, git commit, дата сборки, окружение.

**GET /api/v1/openapi.json**

Машиночитаемая OpenAPI 3.1 спецификация.

**GET /api/v1/docs**

Swagger UI — интерактивная документация.

### 3.2. Articles (статьи help-центра и wiki)

**GET /api/v1/articles**

Список статей. Параметры: category, audience, scope (по умолчанию вычисляется из токена), language, cursor, limit. Cursor-based пагинация.

**GET /api/v1/articles/{slug}**

Полная статья по человекочитаемому slug. Поддержка ETag/If-None-Match. Содержит markdown + html-рендеринг + meta (updated_at, related).

**GET /api/v1/articles/{slug}/related**

Связанные статьи по тегам и категории. Возвращает топ-N (по умолчанию 5).

**POST /api/v1/articles/search**

Полнотекстовый поиск с фильтрами. Параметры в body: q, filters, sort, cursor, limit. Возвращает результаты с подсветкой совпадений.

**POST /api/v1/articles**

Создание статьи. Требует scope staff_support+. Все поля в body. Возвращает созданную статью с присвоенным slug и id.

**PUT /api/v1/articles/{id}**

Полное обновление статьи (идемпотентное). Создаёт новую запись в истории версий.

**PATCH /api/v1/articles/{id}**

Частичное обновление (например, только теги или статус).

**DELETE /api/v1/articles/{id}**

Soft delete (status = ARCHIVED). Физическое удаление — отдельный admin endpoint.

**GET /api/v1/articles/{id}/history**

История изменений статьи. Кто, когда, что изменил.

### 3.3. Categories и tags

**GET /api/v1/categories**

Дерево категорий help-центра.

**GET /api/v1/tags**

Список тегов с количеством статей. Параметр q для autocomplete.

### 3.4. Documents (юридические и др. документы)

**GET /api/v1/documents**

Список документов. Параметры: category (A-F из БЗ v1.2 раздел 3.1), counterparty, status, cursor, limit.

**GET /api/v1/documents/{id}**

Метаданные документа без файла.

**GET /api/v1/documents/{id}/files/{format}**

Скачать файл документа. format ∈ {docx, pdf, html}. Возвращает 302 Redirect на временный signed URL MinIO с TTL 5 минут.

**GET /api/v1/documents/templates**

Шаблоны документов (категория F): шаблоны писем, претензий, актов.

**POST /api/v1/documents**

Создание записи документа. Файл загружается отдельным запросом.

**POST /api/v1/documents/{id}/files**

Multipart upload файла к существующему документу. Возвращает version_id.

### 3.5. Premises Cards (карточки квартир)

**GET /api/v1/premises-cards/{premises_id}**

Расширенная карточка квартиры (см. БЗ v1.2 раздел 5). Отдаваемые поля зависят от scope: гость не видит коды парадных, Wi-Fi пароль и т.д.; наниматель данной квартиры — видит.

**PUT /api/v1/premises-cards/{premises_id}**

Обновление карточки. Требует scope staff_support+ или landlord (для своих).

**GET /api/v1/premises-cards/{premises_id}/financial**

Финансовый блок отдельно (см. БЗ v1.2 раздел 5.2). Только для landlord (свой) или staff.

### 3.6. Chat (AI-чат поверх базы знаний)

**POST /api/v1/chat/sessions**

Создать новую сессию чата. Возвращает session_id с TTL 30 минут.

**GET /api/v1/chat/sessions/{session_id}**

Получить историю сессии.

**POST /api/v1/chat/sessions/{session_id}/messages**

Отправить сообщение в чат. Стриминг ответа через Server-Sent Events (SSE). Поддерживается Idempotency-Key.

**POST /api/v1/chat/sessions/{session_id}/feedback**

Поставить 👍/👎 на конкретный ответ. Опциональный комментарий.

**POST /api/v1/chat/sessions/{session_id}/escalate**

Запрос эскалации на оператора. Возвращает ticket_id и передаёт историю сессии в систему поддержки.

**DELETE /api/v1/chat/sessions/{session_id}**

Удалить сессию и её историю (право пользователя на удаление по ФЗ-152).

### 3.7. Search (универсальный поиск)

**POST /api/v1/search**

Поиск по всему контенту: статьи, документы, карточки квартир, регламенты (с учётом scope). Hybrid: vector + full-text. Возвращает разнородные результаты с типом каждого. Используется внутри чата и в инлайн-поиске.

### 3.8. Webhooks

**GET /api/v1/webhooks**

Список зарегистрированных webhook URL для клиента.

**POST /api/v1/webhooks**

Зарегистрировать новый webhook. Body: url, events, secret (опционально, генерируется если не передан).

**DELETE /api/v1/webhooks/{id}**

Отозвать webhook.

**POST /api/v1/webhooks/{id}/test**

Тестовая отправка события на URL (для отладки на стороне потребителя).

### 3.9. Admin (администрирование kb-модуля)

Все эндпоинты требуют scope = staff_admin или specific admin-permissions. Полный объём заложен в v1.0 — для управления модулем без обращения к разработчикам.

#### 3.9.1. Управление сотрудниками kb

Здесь — сотрудники reHome с правами в kb-модуле (редакторы статей, проверяющие, администраторы). Конечные пользователи rehome.one живут в основной системе, не здесь.

**GET /api/v1/admin/users**

Список сотрудников с правами в kb. Фильтры: role, status.

**POST /api/v1/admin/users**

Добавить сотрудника. Идемпотентно (по email).

**GET /api/v1/admin/users/{user_id}**

Карточка сотрудника.

**PATCH /api/v1/admin/users/{user_id}**

Изменить роль, permissions или статус.

**DELETE /api/v1/admin/users/{user_id}**

Деактивация (soft delete). Отзывает все доступы, переводит в ARCHIVED.

#### 3.9.2. Аудит-лог

**GET /api/v1/admin/audit-log**

Журнал всех действий в kb-модуле. Хранение 5 лет (ФЗ-152). Фильтры: actor, action, entity, severity, период. Cursor-пагинация.

**POST /api/v1/admin/audit-log/export**

Запуск экспорта в CSV/JSON (фоновая задача). Возвращает task_id. Сам экспорт также фиксируется в аудит-логе (аудит аудита).

#### 3.9.3. Запросы субъектов ПДн (ФЗ-152)

Реестр запросов пользователей на предоставление / исправление / удаление / передачу персональных данных. Срок ответа — 30 дней по ст. 14 ФЗ-152. Просроченные подсвечиваются.

**GET /api/v1/admin/personal-data/requests**

Список заявок с фильтрами по статусу и типу.

**GET /api/v1/admin/personal-data/requests/{id}**

Карточка заявки.

**PATCH /api/v1/admin/personal-data/requests/{id}**

Обработка заявки: перевод в IN_PROGRESS / COMPLETED / REJECTED, добавление resolution_note и вложений.

#### 3.9.4. Security инциденты

**GET /api/v1/admin/security-incidents**

Реестр security-событий: попытки обхода прав, утечки, подозрительная активность. Часть событий — автоматически от системы мониторинга, часть — заведены вручную.

**PATCH /api/v1/admin/security-incidents/{id}**

Обновление статуса, фиксация уведомления РКН (24/72 часа по ФЗ-152), resolution_note.

#### 3.9.5. Системные настройки

**GET /api/v1/admin/system-config**

Текущие настройки: rate limits, feature flags, LLM-конфигурация, модерация, webhooks.

**PATCH /api/v1/admin/system-config**

Изменение настроек на лету (без деплоя). Все изменения логируются в аудит.

#### 3.9.6. LLM-провайдеры и eval-стенд

Управление AI-провайдерами и проведение экспериментов по выбору модели (см. документ Чат-поиск ТЗ v2, раздел 3).

**GET /api/v1/admin/llm/providers**

Список подключённых провайдеров (Yandex, GigaChat, Saiga и т.д.) с health-status и стоимостью.

**PUT /api/v1/admin/llm/active**

Переключение активного провайдера. Требует MFA-челлендж (заголовок X-MFA-Token).

**GET /api/v1/admin/llm/eval-runs**

История прогонов eval-стенда с результатами по каждому провайдеру.

**POST /api/v1/admin/llm/eval-runs**

Запуск нового прогона eval (фоновая задача).

#### 3.9.7. Операции с инфраструктурой

**DELETE /api/v1/admin/cache**

Инвалидация кеша по scope (all / articles / documents / premises_cards / search).

**POST /api/v1/admin/reindex**

Принудительная переиндексация vector + full-text. Долгая фоновая операция.

#### 3.9.8. Сводная аналитика

**GET /api/v1/admin/stats**

Метрики kb-модуля за период: запросы (всего, по эндпоинтам, по статусам), чат (сессии, containment rate, NPS), контент (статьи, документы, на ревью), security (открытые инциденты, просроченные ПДн-запросы).

#### 3.9.9. Фоновые задачи

**GET /api/v1/admin/tasks/{task_id}**

Универсальный endpoint для отслеживания асинхронных операций: экспорт, переиндексация, eval. Возвращает status, progress_percent, result_url по завершении.

### 3.10. Collaborators (коллаборанты — внешние исполнители)

Управление сущностью Collaborator — внешними исполнителями платформы reHome (УК/ТСЖ, аварийные службы, клининг, переезды, ремонт, страховые, IT-провайдеры). Подробно — в документе «База знаний v1.4», раздел 10.

#### 3.10.1. CRUD коллаборантов

**GET /api/v1/collaborators**

Список коллаборантов с фильтрами по типу, финансовой группе, статусу, географии. Может фильтроваться по premises_id — вернёт только обслуживающих этот объект. Видимость зависит от scope.

**POST /api/v1/collaborators**

Завести коллаборанта. Создаётся в статусе DRAFT (если не указано) или PENDING_REVIEW (для группы D — управляющих компаний — переходит сразу в ACTIVE).

**GET /api/v1/collaborators/{id}**

Карточка коллаборанта. Состав полей зависит от scope: гость видит только публичные контакты, staff_admin — полный аудит и historical.

**PATCH /api/v1/collaborators/{id}**

Частичное обновление. Изменение типа или финансовой группы — только администратором, фиксируется в аудит-логе.

**DELETE /api/v1/collaborators/{id}**

Архивация (soft delete). Привязки к объектам сохраняются для исторического контекста, но при назначении новых заявок коллаборант не предлагается.

#### 3.10.2. Жизненный цикл коллаборанта

**POST /api/v1/collaborators/{id}/activate**

Активация (DRAFT/PENDING_REVIEW → ACTIVE). Требует выполнения условий: counterparty_check = CLEAN, заполнен contract_document_id (для групп A/B/C), назначен responsible_internal. При несоблюдении — 422 с описанием.

**POST /api/v1/collaborators/{id}/suspend**

Временная приостановка с указанием причины и опциональной даты восстановления.

#### 3.10.3. Аналитика

**GET /api/v1/collaborators/{id}/metrics**

Метрики работы за период: количество заказов (по статусам), выручка (для группы B), SLA, средний рейтинг, жалобы.

#### 3.10.4. Привязка к объектам (PremisesCollaborator)

**GET /api/v1/premises/{premises_id}/collaborators**

Все коллаборанты, обслуживающие данный объект: УК, аварийки, рекомендуемые мастера. Видимость публичных контактов — для нанимателя данной квартиры.

**POST /api/v1/premises/{premises_id}/collaborators**

Назначить коллаборанта на объект с указанием роли (default_uk, emergency_water, plumber и т.п.) и приоритета.

**DELETE /api/v1/premises/{premises_id}/collaborators/{collaborator_id}**

Отвязать коллаборанта.

#### 3.10.5. Отзывы пользователей

**GET /api/v1/collaborators/{id}/reviews**

Отзывы и рейтинги. Публично доступны (с маскированием имени).

**POST /api/v1/collaborators/{id}/reviews**

Оставить отзыв. Доступно tenant/landlord, у которых был завершённый заказ через этого коллаборанта.

#### 3.10.6. Заказы услуг (Service Orders)

Заказы пользователей у коллаборантов финансовой группы B (с оплатой через платформу).

**GET /api/v1/service-orders**

Список заказов. Tenant/landlord — свои, staff — все по фильтрам.

**POST /api/v1/service-orders**

Создать заказ. Деньги пользователя удерживаются в эскроу (HOLD), уведомление коллаборанту. После выполнения (COMPLETED) — выплата за вычетом комиссии.

**GET /api/v1/service-orders/{id}**

Карточка заказа.

**POST /api/v1/service-orders/{id}/cancel**

Отмена. Возврат средств зависит от стадии (до ACCEPTED — полный, после — по правилам коллаборанта).

#### 3.10.7. Онбординг и управление кабинетом

Реализация принятой UX-модели: коллаборант сам выбирает уровень кабинета (см. ПЗ «База знаний v1.4» раздел 10.8.1).

**POST /api/v1/collaborators/onboarding**

Публичная форма самостоятельной заявки на rehome.one/partners. Без авторизации. Принимает данные коллаборанта + желаемый portal_access_level + контакт заявителя. Создаёт карточку в статусе PENDING_REVIEW. Оператор reHome проверяет и активирует.

**PUT /api/v1/collaborators/{id}/portal-access**

Смена уровня кабинета. Понижение (FULL → LIGHT, LIGHT → NONE) — в любой момент. Повышение (NONE → LIGHT, LIGHT → FULL) — только после первой успешной операции через платформу или одобрения оператором (422 если условия не выполнены). История смен сохраняется в карточке.

## 4. Формат обмена данными

### 4.1. Запросы

- Content-Type: application/json; charset=utf-8 для всех мутаций

- Content-Type: multipart/form-data только для загрузки файлов

- Accept: application/json — по умолчанию

- Accept: text/event-stream — для SSE (чат)

- Accept-Language: ru, en — выбор языка ответов (для статей и сообщений об ошибках)

### 4.2. Стандартные заголовки

| **Заголовок**   | **Назначение**                                                                         | **Обязательность**                   |
|-----------------|----------------------------------------------------------------------------------------|--------------------------------------|
| Authorization   | Bearer токен (m2m или user)                                                            | Обязателен для защищённых эндпоинтов |
| X-Request-Id    | UUID для трассировки. Если не передан — генерируется сервером, возвращается в response | Рекомендуется                        |
| X-Client-Id     | Идентификатор клиента (для m2m, и опционально для browser)                             | Обязателен для m2m                   |
| Idempotency-Key | UUID для повторных POST/PATCH. Сервер кеширует ответ на 24ч                            | Рекомендуется для мутаций            |
| X-CSRF-Token    | CSRF-токен (double-submit cookie pattern)                                              | Обязателен для browser-mutations     |
| If-None-Match   | ETag предыдущей версии ресурса                                                         | Опционально                          |
| Accept-Encoding | gzip, br — сервер поддерживает оба                                                     | Рекомендуется                        |

### 4.3. Ответы — единый формат

Все ответы — JSON. Структура успешного ответа:

{  
"data": \<object \| array\>,  
"meta": {  
"request_id": "7b3a8f1e-...",  
"api_version": "1.4.2",  
"timestamp": "2026-05-11T14:32:15Z"  
},  
"pagination": { // только для list-эндпоинтов  
"cursor_next": "eyJpZCI6...",  
"cursor_prev": null,  
"has_more": true,  
"total_estimate": 142 // приблизительная оценка, не точное значение  
}  
}

### 4.4. Ошибки — RFC 7807 (Problem Details)

Все ошибки в формате application/problem+json:

{  
"type": "https://api.rehome.one/kb/errors/access-denied",  
"title": "Access denied",  
"status": 403,  
"detail": "Запрашиваемая статья требует роль staff_support, у вас scope=tenant",  
"instance": "/api/v1/articles/internal-regulation-005",  
"request_id": "7b3a8f1e-...",  
"code": "ACCESS_DENIED",  
"errors": \[ // опционально, для validation errors  
{  
"field": "category",  
"code": "INVALID_VALUE",  
"message": "Допустимые значения: faq, regulation, guide, policy"  
}  
\]  
}

#### 4.4.1. HTTP коды и их семантика

| **Код**                   | **Когда возвращается**                                        | **Действие потребителя**                          |
|---------------------------|---------------------------------------------------------------|---------------------------------------------------|
| 200 OK                    | Успех чтения или обновления                                   | —                                                 |
| 201 Created               | Успех создания ресурса                                        | Использовать возвращённый id                      |
| 204 No Content            | Успех без тела ответа (DELETE)                                | —                                                 |
| 304 Not Modified          | Ресурс не изменился с last ETag                               | Использовать кеш                                  |
| 400 Bad Request           | Ошибка валидации payload                                      | Исправить запрос                                  |
| 401 Unauthorized          | Нет токена или истёк                                          | Получить новый токен                              |
| 403 Forbidden             | Токен валиден, но scope не позволяет                          | Не повторять — обратиться к admin                 |
| 404 Not Found             | Ресурс не существует ИЛИ scope не позволяет его видеть        | —                                                 |
| 409 Conflict              | Конфликт версий (If-Match) или дубль                          | Получить актуальную версию и повторить            |
| 422 Unprocessable Entity  | Семантическая ошибка (например, недопустимый переход статуса) | Исправить логику                                  |
| 429 Too Many Requests     | Превышен rate limit                                           | Подождать Retry-After секунд                      |
| 500 Internal Server Error | Баг на стороне kb-API                                         | Повторить с backoff, эскалировать после 3 попыток |
| 502/503/504               | Временная проблема (зависимость / перегрузка)                 | Повторить с экспоненциальным backoff              |


> **📌 Маскировка 404 vs 403**
>
> Когда пользователь запрашивает ресурс, который существует, но его scope не позволяет — возвращается 404 Not Found, не 403. Это защита от утечки информации о существовании ресурса. Исключение: явно публичные ресурсы (категория PUBLIC), где 403 даёт понять «требуется логин».


### 4.5. Cursor-based пагинация

Все list-эндпоинты используют cursor-based пагинацию, не offset:

GET /api/v1/articles?limit=20&cursor=eyJpZCI6IjQyIiwic29ydCI6Ii0xMjM0NTYifQ==  
  
Response:  
{  
"data": \[...\],  
"pagination": {  
"cursor_next": "eyJpZCI6IjYyIiwi...", // null если страниц больше нет  
"cursor_prev": "eyJpZCI6IjIyIiwi...",  
"has_more": true,  
"total_estimate": 142  
}  
}

Cursor — base64-encoded JSON с полями id и sort_value. Сервер декодирует, проверяет валидность, конструирует SQL WHERE.

### 4.6. Стриминг чата (SSE)

Endpoint POST /api/v1/chat/sessions/{session_id}/messages возвращает text/event-stream:

POST /api/v1/chat/sessions/abc/messages  
Accept: text/event-stream  
Content-Type: application/json  
  
{"content": "Что такое сервисный платёж?"}  
  
Response:  
HTTP/1.1 200 OK  
Content-Type: text/event-stream  
Cache-Control: no-cache  
  
event: message-start  
data: {"message_id": "msg-123", "created_at": "..."}  
  
event: chunk  
data: {"text": "Сервисный платёж"}  
  
event: chunk  
data: {"text": " — это невозвратный платёж"}  
  
event: chunk  
data: {"text": ", вносимый при заезде."}  
  
event: citation  
data: {"source": {"type": "article", "slug": "service-fee", "title": "..."}}  
  
event: message-end  
data: {"message_id": "msg-123", "total_tokens": 142, "duration_ms": 2841}  
  
event: done  
data: {}

## 5. Webhooks — события

Платформа kb отправляет HTTP POST на зарегистрированный URL при наступлении следующих событий:

### 5.1. Перечень событий

| **Событие**           | **Когда отправляется**                                  | **Payload**                                             |
|-----------------------|---------------------------------------------------------|---------------------------------------------------------|
| article.published     | Статья переведена в статус PUBLISHED                    | {article: {id, slug, title, category}}                  |
| article.updated       | Статья обновлена                                        | {article: {id, slug, version}, changed_fields: \[...\]} |
| article.archived      | Статья переведена в ARCHIVED                            | {article: {id, slug}}                                   |
| document.created      | Создан новый документ                                   | {document: {id, title, category}}                       |
| document.signed       | Документ подписан всеми сторонами                       | {document: {id}, signatures: \[...\]}                   |
| chat.escalated        | Пользователь запросил оператора в чате                  | {session_id, user_id, history_url}                      |
| chat.no_answer        | Чат не смог ответить на вопрос (для аналитики)          | {session_id, query, retrieved_sources}                  |
| search.popular_query  | Запрос стал часто повторяющимся без ответа (раз в день) | {queries: \[...\]}                                      |
| premises_card.updated | Изменены данные карточки квартиры                       | {premises_id, changed_fields: \[...\]}                  |
| audit.security_event  | Зафиксирован security-инцидент (попытка обхода прав)    | {event_type, severity, details}                         |

### 5.2. Формат payload

POST \<callback-url\>  
Content-Type: application/json  
X-Webhook-Signature: sha256=HMAC(secret, body)  
X-Webhook-Event: article.published  
X-Webhook-Delivery: \<uuid идентификатор доставки\>  
X-Webhook-Timestamp: 1715441234  
  
{  
"event": "article.published",  
"event_id": "evt-7b3a8f1e-...", // для дедупликации  
"occurred_at": "2026-05-11T14:32:15Z",  
"api_version": "1.4.2",  
"data": {  
"article": {  
"id": "art-abc",  
"slug": "service-fee",  
"title": "Что такое сервисный платёж",  
"category": "faq",  
"audience": "tenant",  
"url": "https://help.rehome.one/articles/service-fee"  
}  
}  
}

### 5.3. Проверка подписи

Получатель обязан проверить подпись для защиты от спуфинга:

\# Python  
import hmac, hashlib  
  
def verify_webhook(secret: bytes, body: bytes, signature_header: str) -\> bool:  
expected = "sha256=" + hmac.new(  
secret, body, hashlib.sha256  
).hexdigest()  
return hmac.compare_digest(expected, signature_header)

### 5.4. Retry и идемпотентность

- Получатель обязан вернуть 2xx в течение 10 секунд. Иначе — retry.

- 5 попыток с задержками: 1s, 5s, 30s, 5min, 30min

- После 5 неудач — событие складывается в Dead Letter Queue, alert администратору

- Получатель обязан дедуплицировать по event_id

## 6. Безопасность

### 6.1. Транспорт

- TLS 1.3 only. TLS 1.2 — допустим до конца 2026 г., далее запрещён.

- HSTS: max-age=31536000; includeSubDomains; preload

- Сертификаты — Let's Encrypt с авто-обновлением, либо корпоративный УЦ

- Для m2m — опционально mTLS (взаимная аутентификация сертификатами)

### 6.2. CORS

Cross-Origin Resource Sharing настроен строго:

- Allow-Origin: только https://rehome.one, https://\*.rehome.one, локальные dev-домены

- Allow-Credentials: true (для cookie-based авторизации)

- Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS

- Allow-Headers: Authorization, X-CSRF-Token, X-Request-Id, X-Client-Id, Idempotency-Key, If-None-Match, Content-Type, Accept, Accept-Language

- Max-Age: 86400 (24 часа кеширование preflight)

### 6.3. CSP для embedded виджета

Если виджет чата встраивается через iframe — заголовки CSP при отдаче виджета:

Content-Security-Policy:  
default-src 'self';  
script-src 'self' 'nonce-{random}';  
style-src 'self' 'unsafe-inline';  
connect-src 'self' https://api.rehome.one;  
frame-ancestors https://rehome.one https://\*.rehome.one;

### 6.4. Rate limiting

| **Сегмент**                  | **Лимит**                 | **Окно**          |
|------------------------------|---------------------------|-------------------|
| Гость по IP                  | 60 запросов / минуту      | Скользящее окно   |
| Авторизованный пользователь  | 300 запросов / минуту     | Скользящее окно   |
| m2m rehome-platform          | 10 000 запросов / минуту  | Скользящее окно   |
| Chat messages (любая роль)   | 30 сообщений / 5 минут    | Защита от спама   |
| Webhook доставка (исходящие) | 100 / секунду на endpoint | Защита получателя |

**Превышение → 429 Too Many Requests с заголовками:**

HTTP/1.1 429 Too Many Requests  
Retry-After: 12  
X-RateLimit-Limit: 60  
X-RateLimit-Remaining: 0  
X-RateLimit-Reset: 1715441246

### 6.5. Защита от типичных атак

- **SQL injection:** только параметризованные запросы через ORM (SQLAlchemy / Django ORM). Прямые SQL — запрещены.

- **NoSQL injection (Qdrant):** только параметризованные filter-выражения, без конкатенации пользовательского ввода.

- **Prompt injection в чате:** входной запрос изолируется в специальные теги, system prompt инструктирует не следовать инструкциям из user input. См. документ Чат-поиск ТЗ v2 раздел 6.3.

- **XSS:** все markdown-статьи рендерятся в HTML на сервере через библиотеку с whitelist (например, bleach для Python). Никакого raw HTML от пользователей.

- **SSRF:** URL в webhooks проверяются: только публичные IP, не RFC 1918, не localhost.

- **DDoS:** rate limiting + CDN перед API + bot-detection.

- **Утечка через ответы:** сериализаторы по умолчанию whitelist полей, не blacklist. Нельзя случайно отдать «лишнее» поле.

### 6.6. Логирование и аудит

Каждый запрос логируется с полями:

- request_id (UUID для трассировки)

- timestamp (UTC, ISO 8601 с миллисекундами)

- method, path

- user_id (если авторизован), client_id, scope

- IP (для гостей), User-Agent

- response status, response time (ms)

- error code (если ошибка)

ВАЖНО: тело запроса и ответа НЕ логируется, если содержит ПДн. Только структура и размер. Для отладки — отдельный debug-режим с маскировкой.

### 6.7. ФЗ-152 — операционная сторона API

- Все сервера API — в РФ

- Endpoint DELETE /api/v1/chat/sessions/{session_id} реализует право на удаление

- Endpoint GET /api/v1/users/me/data (в v1.1) реализует право на получение собственных данных

- Логи запросов с ПДн — обезличиваются через 90 дней, удаляются через 1 год

- Audit-лог security-событий хранится 5 лет

## 7. Производительность и SLA

### 7.1. Целевые показатели

| **Метрика**                           | **p50** | **p95** | **p99** |
|---------------------------------------|---------|---------|---------|
| GET /api/v1/articles/{slug} (cached)  | 20ms    | 60ms    | 200ms   |
| GET /api/v1/articles/{slug} (cold)    | 80ms    | 300ms   | 800ms   |
| POST /api/v1/articles/search          | 100ms   | 400ms   | 1s      |
| POST /api/v1/search (hybrid)          | 200ms   | 600ms   | 1.5s    |
| POST /api/v1/chat/.../messages — TTFB | 800ms   | 2s      | 4s      |
| POST /api/v1/chat/.../messages — full | 3s      | 8s      | 15s     |
| Webhook delivery                      | 200ms   | 1s      | 3s      |

### 7.2. Доступность

- SLA: 99.5% (43.8 минут downtime в месяц)

- Плановое обслуживание: уведомление за 7 дней, окно — ночное время МСК

- Деградация: при недоступности kb-search чат отключается, остальные endpoint'ы работают

- Health-check каждые 30 секунд через /health и /ready

### 7.3. Кеширование

- HTTP-кеширование: ETag на GET-запросах, Cache-Control: public, max-age=300 для статей

- CDN перед API: 1 минута для articles list, 5 минут для отдельной статьи

- Server-side cache (Redis): 1 час для статей, 5 минут для search

- Инвалидация кеша: по webhook от kb-wiki при изменении статьи

### 7.4. Мониторинг

- Prometheus метрики на /metrics (только для internal scrape, не публичный)

- Метрики: rps, latency percentiles, error rate, queue depth, dependency health

- Sentry: все 5xx ошибки + 4xx с подозрительной частотой

- Grafana дашборд для каждого consumer (rehome-platform, mobile и т.д.)

- Alerts: error rate \> 1% в течение 5 минут, p95 latency \> целевой в течение 10 минут

## 8. Версионирование и обратная совместимость

### 8.1. Что считается breaking change

- Удаление endpoint'а

- Изменение HTTP-метода или URL endpoint'а

- Удаление поля из response

- Изменение типа поля (int → string)

- Добавление обязательного параметра request

- Изменение семантики поля (то же имя, другое значение)

- Изменение значений enum (удаление варианта)

- Изменение HTTP-кода для существующей семантики (200 → 201 для того же запроса)

### 8.2. Что считается non-breaking

- Добавление нового endpoint'а

- Добавление нового поля в response (потребитель должен игнорировать неизвестные)

- Добавление необязательного параметра в request

- Добавление нового значения enum (если потребитель обрабатывает unknown)

- Улучшение производительности

- Расширение лимитов rate limiting

### 8.3. Процедура breaking change

6.  RFC: создаётся ADR с описанием изменения, причины, альтернатив

7.  Согласование с консьюмерами: rehome.one команда смотрит, оценивает свои усилия

8.  Запуск новой версии (v2) параллельно со старой (v1)

9.  Уведомление: заголовок Deprecation: true и Sunset: \<дата\> на старой версии

10. Минимум 6 месяцев параллельной работы

11. После Sunset — старая версия отдаёт 410 Gone с подробным сообщением о миграции

### 8.4. Changelog

Каждая версия документирована в /api/v1/changelog. Формат — Keep a Changelog:

\## \[1.4.2\] - 2026-05-11  
\### Added  
- POST /api/v1/articles/{id}/translate (P2 feature, beta)  
- Поле seo_metadata в article.response  
  
\### Changed  
- Default limit для GET /api/v1/articles: 20 → 50  
  
\### Deprecated  
- Header X-Legacy-Token — использовать Authorization вместо. Sunset: 2026-11-01  
  
\### Fixed  
- Утечка памяти при долгих SSE сессиях  
  
\### Security  
- Усилены CORS правила для рекомендаций

## 9. Тестирование контракта

### 9.1. Contract tests

OpenAPI-спецификация — источник истины. На её основе генерируются:

- Mock-сервер для разработки rehome.one (можно начинать интеграцию до готовности backend)

- Автотесты контракта на стороне backend: каждый response валидируется по схеме

- Автотесты контракта на стороне consumer: каждый запрос проверяется на соответствие схеме

- Postman collection для ручного тестирования

- Клиентские SDK на TypeScript и Python (через openapi-generator)

### 9.2. Consumer-driven contract tests

Pact — рекомендуемый инструмент. rehome.one команда пишет тесты «как я ожидаю, что API себя ведёт». Эти тесты прогоняются на стороне kb-API при каждом коммите. Если контракт сломан — CI красный, merge заблокирован.

### 9.3. Тестовые fixture-данные

kb-API в среде dev и staging содержит фиксированный набор тестовых данных:

- 100 статей FAQ в разных категориях

- 10 типовых документов (оферта, договор, политика)

- 5 тестовых квартир с полными карточками

- Тестовые пользователи каждой роли

- Идемпотентные id (одинаковые между деплоями) — для воспроизводимости тестов

### 9.4. Smoke-тесты в продакшне

После каждого деплоя — автоматические smoke-тесты:

- GET /api/v1/health → 200

- GET /api/v1/articles?limit=1 → 200, валидная схема

- POST /api/v1/search с тестовым запросом → 200, есть результаты

- POST /api/v1/chat/sessions → 200, возвращает session_id

При провале — автоматический rollback на предыдущую версию.

## 10. Дорожная карта внедрения API

### 10.1. Решение: полный объём в v1.0

API проектируется с полным набором функций в первой мажорной версии (v1.0), включая администрирование. Это решение принципиально отличается от поэтапного подхода и имеет последствия:

- **Плюс:** стабильный контракт с самого начала. Потребителям не нужно адаптироваться к расширениям. Партнёрам и rehome.one команде даётся полная карта возможностей.

- **Плюс:** OpenAPI спецификация — финальная. Mock-сервер генерируется один раз и охватывает все сценарии. SDK генерируются один раз.

- **Минус:** увеличенный объём разработки backend. 40 эндпоинтов вместо 24. Требует больше времени до полной готовности (12-14 недель вместо 4).

- **Митигация:** поэтапная реализация backend ВНУТРИ v1.0. Спецификация финальная, но эндпоинты включаются last-to-first по приоритету: сначала Read + Chat (для рендеринга и пользовательского чата), затем Write (для редакторов), потом Admin (для управления). На фронтенде используется mock-сервер для эндпоинтов, не реализованных backend.

### 10.2. Внутренние этапы реализации (внутри v1.0)

Спецификация одна и финальная. Backend реализуется поэтапно:

| **Этап реализации**       | **Эндпоинты**                                                                                                                  | **Срок** | **Что разблокирует**                                                           |
|---------------------------|--------------------------------------------------------------------------------------------------------------------------------|----------|--------------------------------------------------------------------------------|
| E1 — Foundation           | Health, version, OpenAPI docs, auth-инфраструктура (Keycloak + middleware)                                                     | 2 нед    | Возможность подключить mock-сервер на полный API                               |
| E2 — Read                 | Articles (GET), Categories, Tags, Documents (GET), Search, Premises Cards (GET)                                                | 3 нед    | SSR help-центра rehome.one, инлайн-подсказки в ЛК                              |
| E3 — Chat MVP             | Chat sessions, messages (SSE), feedback, escalate                                                                              | 4 нед    | Виджет чата на сайте, эскалация в поддержку                                    |
| E4 — Write для редакторов | Articles (POST/PUT/PATCH/DELETE), Documents (POST), Categories admin, Premises Cards (PUT)                                     | 3 нед    | Редакторы наполняют базу, не привлекая разработчиков                           |
| E5 — Webhooks             | Webhooks CRUD + delivery infrastructure                                                                                        | 2 нед    | Уведомления rehome.one об изменениях контента                                  |
| E6 — Admin                | User management, audit log, PD requests, security incidents, system config, LLM management, eval, cache, reindex, stats, tasks | 4 нед    | Полная автономность модуля, compliance, ФЗ-152 операционка                     |
| E7 — Collaborators        | CRUD коллаборантов, жизненный цикл, PremisesCollaborator, отзывы, ServiceOrder с эскроу                                        | 4 нед    | Подключение УК/ТСЖ, аварийных служб, монетизация через заказы клининга/ремонта |

*Итого: ~22 недели до полной реализации v1.0. С первой недели — mock-сервер на полный объём для команды rehome.one. К E2 (5-я неделя) — первые реальные эндпоинты в продакшне.*

### 10.3. Definition of Done для v1.0

- OpenAPI спецификация опубликована и проходит линтер (Spectral)

- Mock-сервер развёрнут на mock.api.rehome.one (для интеграции с rehome.one с E1)

- Backend реализован, все 51 эндпоинт v1.0 покрыты тестами

- CI: contract tests, security scan, performance test, тесты scope (попытки обхода)

- Swagger UI доступен на /api/v1/docs

- Аутентификация m2m работает через Keycloak

- Аутентификация browser через cookie-JWT работает с CSRF-защитой

- Rate limiting настроен по сегментам (guest / user / m2m)

- Логирование, аудит-лог и мониторинг настроены

- Smoke-тесты в продакшне после каждого деплоя

- Документация для разработчиков rehome.one (этот документ + примеры использования + Quickstart)

- DPA / ФЗ-152 чек-лист подписан

- SDK для TypeScript и Python сгенерированы и опубликованы во внутреннем NPM/PyPI

- Postman collection экспортирована

- Все 16 admin-эндпоинтов протестированы, доступ только staff_admin

- MFA-поток для критических admin-операций работает

# Приложение A — OpenAPI 3.1 спецификация (фрагмент)

Полная OpenAPI спецификация поставляется отдельным файлом openapi.yaml. Ниже — её ключевые части для ознакомления. Этот файл — машиночитаемый, источник истины, по нему генерируется код.

**A.1. Основа спецификации**

openapi: 3.1.0  
info:  
title: reHome Knowledge Base API  
version: 1.0.0  
description: \|  
Публичный API модуля базы знаний платформы reHome.  
Полное описание — в документе «API базы знаний reHome v1.0».  
contact:  
name: reHome Engineering  
email: engineering@rehome.one  
license:  
name: Proprietary  
  
servers:  
- url: https://api.rehome.one/kb  
description: Production  
- url: https://api.staging.rehome.one/kb  
description: Staging  
- url: http://localhost:8000/kb  
description: Local development  
  
security:  
- BearerAuth: \[\]  
- CookieAuth: \[\]  
  
tags:  
- name: Health  
description: Health checks и метаданные  
- name: Articles  
description: Статьи help-центра и wiki  
- name: Documents  
description: Юридические и прочие документы  
- name: Premises Cards  
description: Карточки сдаваемых квартир  
- name: Chat  
description: AI-чат по базе знаний  
- name: Search  
description: Универсальный поиск  
- name: Webhooks  
description: Управление webhook подписками

**A.2. Схемы безопасности**

components:  
securitySchemes:  
BearerAuth:  
type: http  
scheme: bearer  
bearerFormat: JWT  
description: \|  
m2m токен (Client Credentials Grant) или user JWT.  
Получить токен: POST /auth/token (kb-auth Keycloak)  
  
CookieAuth:  
type: apiKey  
in: cookie  
name: kb_session  
description: \|  
User session JWT в HttpOnly Secure cookie.  
Устанавливается при логине в rehome.one.

**A.3. Общие схемы данных**

components:  
schemas:  
Error:  
type: object  
required: \[type, title, status, code\]  
properties:  
type:  
type: string  
format: uri  
title: { type: string }  
status: { type: integer }  
detail: { type: string }  
instance: { type: string }  
request_id: { type: string, format: uuid }  
code: { type: string, enum: \[VALIDATION, ACCESS_DENIED, NOT_FOUND,  
RATE_LIMIT, CONFLICT, INTERNAL_ERROR\] }  
errors:  
type: array  
items:  
type: object  
properties:  
field: { type: string }  
code: { type: string }  
message: { type: string }  
  
Pagination:  
type: object  
properties:  
cursor_next: { type: string, nullable: true }  
cursor_prev: { type: string, nullable: true }  
has_more: { type: boolean }  
total_estimate: { type: integer }  
  
Meta:  
type: object  
required: \[request_id, api_version, timestamp\]  
properties:  
request_id: { type: string, format: uuid }  
api_version: { type: string }  
timestamp: { type: string, format: date-time }  
  
AccessLevel:  
type: string  
enum: \[PUBLIC, LOGGED, AGENT, STAFF, LEGAL, HR_RESTRICTED\]  
  
Audience:  
type: string  
enum: \[all, guest, tenant, landlord, agent, staff\]  
  
Language:  
type: string  
enum: \[ru, en\]  
default: ru

**A.4. Схема Article**

components:  
schemas:  
Article:  
type: object  
required: \[id, slug, title, category, audience, access_level,  
created_at, updated_at, status\]  
properties:  
id: { type: string, format: uuid }  
slug: { type: string, pattern: "^\[a-z0-9-\]+\$" }  
title: { type: string, maxLength: 200 }  
short_answer: { type: string, maxLength: 300 }  
body_markdown: { type: string }  
body_html: { type: string }  
category:  
type: string  
enum: \[faq, regulation, guide, policy, document, glossary\]  
audience: { \$ref: '#/components/schemas/Audience' }  
access_level: { \$ref: '#/components/schemas/AccessLevel' }  
tags:  
type: array  
items: { type: string }  
related:  
type: array  
items: { type: string, format: uuid }  
author: { type: string }  
status:  
type: string  
enum: \[DRAFT, PUBLISHED, ARCHIVED\]  
language: { \$ref: '#/components/schemas/Language' }  
created_at: { type: string, format: date-time }  
updated_at: { type: string, format: date-time }  
published_at: { type: string, format: date-time, nullable: true }

**A.5. Эндпоинты Articles — фрагмент**

paths:  
/api/v1/articles:  
get:  
tags: \[Articles\]  
summary: Список статей  
operationId: listArticles  
parameters:  
- name: category  
in: query  
schema: { type: string }  
- name: audience  
in: query  
schema: { \$ref: '#/components/schemas/Audience' }  
- name: cursor  
in: query  
schema: { type: string }  
- name: limit  
in: query  
schema: { type: integer, minimum: 1, maximum: 100, default: 20 }  
responses:  
'200':  
description: Успех  
headers:  
ETag: { schema: { type: string } }  
X-RateLimit-Remaining: { schema: { type: integer } }  
content:  
application/json:  
schema:  
type: object  
required: \[data, meta, pagination\]  
properties:  
data:  
type: array  
items: { \$ref: '#/components/schemas/Article' }  
meta: { \$ref: '#/components/schemas/Meta' }  
pagination: { \$ref: '#/components/schemas/Pagination' }  
'400': { \$ref: '#/components/responses/BadRequest' }  
'429': { \$ref: '#/components/responses/RateLimit' }  
security: \[\] \# публичный endpoint, разрешён без токена  
  
/api/v1/articles/{slug}:  
get:  
tags: \[Articles\]  
summary: Статья по slug  
operationId: getArticleBySlug  
parameters:  
- name: slug  
in: path  
required: true  
schema: { type: string }  
- name: If-None-Match  
in: header  
schema: { type: string }  
responses:  
'200':  
description: Успех  
headers:  
ETag: { schema: { type: string } }  
Cache-Control: { schema: { type: string } }  
content:  
application/json:  
schema:  
type: object  
properties:  
data: { \$ref: '#/components/schemas/Article' }  
meta: { \$ref: '#/components/schemas/Meta' }  
'304':  
description: Не изменилось с last ETag  
'404': { \$ref: '#/components/responses/NotFound' }

**A.6. Эндпоинт Chat — фрагмент**

paths:  
/api/v1/chat/sessions/{session_id}/messages:  
post:  
tags: \[Chat\]  
summary: Отправить сообщение в чат  
operationId: sendChatMessage  
parameters:  
- name: session_id  
in: path  
required: true  
schema: { type: string, format: uuid }  
- name: Idempotency-Key  
in: header  
schema: { type: string, format: uuid }  
- name: Accept  
in: header  
schema:  
type: string  
enum: \[application/json, text/event-stream\]  
default: text/event-stream  
requestBody:  
required: true  
content:  
application/json:  
schema:  
type: object  
required: \[content\]  
properties:  
content:  
type: string  
minLength: 1  
maxLength: 2000  
attachments:  
type: array  
items: { type: string, format: uuid }  
responses:  
'200':  
description: SSE-стрим с ответом  
content:  
text/event-stream:  
schema:  
type: string  
description: \|  
События: message-start, chunk, citation,  
message-end, error, done.  
application/json:  
schema:  
type: object  
properties:  
message_id: { type: string }  
content: { type: string }  
citations: { type: array }  
'429': { \$ref: '#/components/responses/RateLimit' }

Полная спецификация (~1500 строк YAML) — отдельный файл openapi.yaml в репозитории kb-api, поддерживается агентами в рамках процесса разработки (см. ТЗ Claude Code v1).

# Приложение B — Примеры использования (curl)

**B.1. Получить список статей FAQ**

curl -X GET 'https://api.rehome.one/kb/api/v1/articles?category=faq&audience=tenant&limit=10' \\  
-H 'Accept: application/json' \\  
-H 'Accept-Language: ru' \\  
-H 'X-Request-Id: 7b3a8f1e-4321-...'

**B.2. Получить конкретную статью с кешированием**

curl -X GET 'https://api.rehome.one/kb/api/v1/articles/service-fee' \\  
-H 'Accept: application/json' \\  
-H 'If-None-Match: "abc123"' \\  
-H 'Accept-Encoding: gzip'

**B.3. m2m авторизация и поиск**

\# Шаг 1: получение токена  
curl -X POST 'https://auth.rehome.one/realms/rehome/protocol/openid-connect/token' \\  
-H 'Content-Type: application/x-www-form-urlencoded' \\  
-d 'grant_type=client_credentials' \\  
-d 'client_id=rehome-platform' \\  
-d 'client_secret=\<секрет\>'  
  
\# Шаг 2: использование токена  
curl -X POST 'https://api.rehome.one/kb/api/v1/search' \\  
-H 'Authorization: Bearer eyJhbGc...' \\  
-H 'Content-Type: application/json' \\  
-d '{  
"query": "когда вносится сервисный платёж",  
"limit": 5,  
"filters": { "audience": "tenant" }  
}'

**B.4. Стриминг чата (Node.js)**

import { EventSource } from 'eventsource';  
  
// 1. Создать сессию  
const session = await fetch(  
'https://api.rehome.one/kb/api/v1/chat/sessions',  
{  
method: 'POST',  
credentials: 'include',  
headers: { 'X-CSRF-Token': csrfToken },  
}  
).then(r =\> r.json());  
  
// 2. Открыть SSE стрим для отправки сообщения  
const response = await fetch(  
\`https://api.rehome.one/kb/api/v1/chat/sessions/\${session.data.id}/messages\`,  
{  
method: 'POST',  
credentials: 'include',  
headers: {  
'Content-Type': 'application/json',  
'Accept': 'text/event-stream',  
'X-CSRF-Token': csrfToken,  
'Idempotency-Key': crypto.randomUUID(),  
},  
body: JSON.stringify({ content: 'Что такое сервисный платёж?' }),  
}  
);  
  
const reader = response.body.getReader();  
const decoder = new TextDecoder();  
while (true) {  
const { value, done } = await reader.read();  
if (done) break;  
const text = decoder.decode(value);  
// Парсинг SSE-событий: event:, data:  
// ... обработка chunk, citation, message-end  
}

**B.5. Регистрация webhook**

curl -X POST 'https://api.rehome.one/kb/api/v1/webhooks' \\  
-H 'Authorization: Bearer eyJ...' \\  
-H 'Content-Type: application/json' \\  
-d '{  
"url": "https://rehome.one/internal/kb-webhooks",  
"events": \["article.published", "article.updated", "chat.escalated"\],  
"description": "Sync с rehome.one main backend"  
}'

# Приложение C — Интеграционные сценарии rehome.one

**C.1. Рендеринг help-центра (SSR)**

Платформа rehome.one рендерит страницы /help/\* на стороне сервера для SEO:

12. Next.js getStaticPaths → GET /api/v1/articles (m2m) → получает slugs

13. На каждый slug при build/revalidate → GET /api/v1/articles/{slug} → markdown + meta

14. Рендерится HTML страница help.rehome.one/\<slug\>

15. Webhook article.updated → re-validate соответствующую страницу через Next.js ISR

**C.2. Чат-виджет на сайте**

Сайт rehome.one встраивает чат-виджет:

16. Загружается скрипт chat-widget.js (хостится в kb-API под /static/widget/)

17. Виджет создаёт сессию: POST /api/v1/chat/sessions (через JWT cookie пользователя)

18. При вводе сообщения — POST /api/v1/chat/sessions/{id}/messages со streaming

19. Виджет рендерит ответ с цитатами + кнопки фидбека

20. При запросе оператора — POST /api/v1/chat/sessions/{id}/escalate, виджет показывает ticket_id

**C.3. Контекстная подсказка в личном кабинете**

Внутри личного кабинета арендатора — кнопка «Что это значит?» рядом с непонятными терминами:

21. Клик по «Что это значит?» с параметром term=service_fee

22. rehome.one фронтенд → GET /api/v1/articles?tags=service-fee&audience=tenant&limit=1

23. Показывается short_answer как tooltip

24. Клик «Подробнее» → ссылка на help.rehome.one/\<slug\>

**C.4. Карточка квартиры в админке**

Сотрудник в /staff открывает объявление:

25. rehome.one /staff → GET /api/v1/premises-cards/{premises_id} (m2m + user scope в JWT)

26. Возвращается полная карточка с финансовым блоком

27. Изменения сотрудника → PUT /api/v1/premises-cards/{premises_id}

28. kb-API сохраняет, отправляет webhook premises_card.updated на rehome.one

29. rehome.one инвалидирует свой кеш

**C.5. Синхронизация документов пользователя**

В личном кабинете показываются договоры пользователя:

30. Личный кабинет → GET /api/v1/documents?related_entity=user:{user_id} (user JWT)

31. Возвращается список документов, отфильтрованный по правам (свой scope)

32. Клик «Скачать» → GET /api/v1/documents/{id}/files/pdf

33. Endpoint возвращает 302 на signed URL в MinIO (TTL 5 минут)

34. Браузер скачивает файл напрямую с MinIO

# Приложение D — Контрольный список разработки API

Используется агентом-разработчиком при создании или модификации эндпоинтов:

**D.1. Дизайн endpoint'а**

- ⬜ URL ресурсо-ориентированный, использует существительные (не глаголы)

- ⬜ HTTP-метод соответствует семантике (GET/POST/PUT/PATCH/DELETE)

- ⬜ Версия в URL: /api/v1/

- ⬜ Параметры пути — обязательные идентификаторы; параметры query — фильтры/опции

- ⬜ Idempotent методы (GET, PUT, DELETE) можно повторять без побочных эффектов

**D.2. Спецификация**

- ⬜ Endpoint описан в openapi.yaml

- ⬜ Все коды ответов перечислены (200, 4xx, 5xx)

- ⬜ Схемы request/response используют существующие компоненты

- ⬜ Описания на русском, грамотные, понятные

- ⬜ operationId уникален и читаем

- ⬜ Tags соответствуют группировке из раздела 3

**D.3. Безопасность**

- ⬜ Указан security: BearerAuth / CookieAuth / \[\] (для public)

- ⬜ access_level фильтрация применена на уровне хранилища

- ⬜ Чувствительные поля скрываются в сериализаторе по scope

- ⬜ Mutating endpoint требует CSRF-токен (для browser)

- ⬜ Rate limit применён

- ⬜ Логирование запроса без ПДн в теле

**D.4. Производительность**

- ⬜ List endpoint использует cursor-based pagination

- ⬜ GET endpoint поддерживает ETag и If-None-Match

- ⬜ Cache-Control headers установлены адекватно

- ⬜ База данных запросы: индексы покрывают WHERE и ORDER BY

- ⬜ Нет N+1 проблемы

**D.5. Тесты**

- ⬜ Контрактный тест: response валидируется по схеме

- ⬜ Тест успешного сценария

- ⬜ Тест 400 (валидация)

- ⬜ Тест 401/403 (авторизация)

- ⬜ Тест 404 (отсутствие ресурса)

- ⬜ Тест rate limit (429)

- ⬜ Тест scope: гость не видит staff контент, и т.д.

- ⬜ Тест idempotency для мутаций

**D.6. Документация**

- ⬜ Пример curl в Приложении B

- ⬜ Если интеграционный сценарий — в Приложении C

- ⬜ Changelog обновлён

- ⬜ Если breaking — открыт RFC, согласовано с rehome.one


> **📌 Главное**
>
> API — это публичный контракт. Каждое решение должно быть обосновано: «зачем именно так, какие альтернативы рассматривались, кто его консьюмеры». OpenAPI спецификация — единственный источник истины. Документ, который вы сейчас читаете — это объяснение и контекст. При расхождениях — приоритет за OpenAPI.

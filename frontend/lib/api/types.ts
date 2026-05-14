/**
 * TypeScript types для backend API responses (UI.1 #75).
 *
 * Handwritten соответствие Pydantic schemas в `backend/src/api/.../schemas.py`.
 * Backlog: автогенерация через `openapi-typescript-codegen` из 04_openapi.yaml
 * после landing'а UI epic.
 *
 * Источники истины:
 * - articles: backend/src/api/articles/schemas.py
 * - chat: backend/src/api/chat/schemas.py
 * - categories: backend/src/api/categories/schemas.py
 * - tags: backend/src/api/tags/schemas.py
 * - documents: backend/src/api/documents/schemas.py
 */

// ============================================================================
// Common

export interface PaginationInfo {
  cursor_next: string | null;
  has_more: boolean;
}

// ============================================================================
// Articles

/**
 * Article в list-endpoint response. Соответствует backend
 * `ArticleSummary` (articles/schemas.py:53-66) — минимальный набор полей,
 * без body_markdown / summary / language / published_at.
 */
export interface ArticleSummary {
  id: string;
  slug: string;
  title: string;
  category: string;
  audience: string;
  access_level: string;
  tags: string[];
  status: string;
  updated_at: string;
}

/**
 * Article в detail-endpoint (`GET /articles/{slug}`) — расширенный
 * набор с content. Backend `ArticleResponse` включает все поля Article
 * model, кроме internal.
 */
export interface Article {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  body_markdown: string;
  category: string;
  audience: string;
  language: string;
  tags: string[];
  access_level: string;
  status: string;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArticlesListResponse {
  data: ArticleSummary[];
  pagination: PaginationInfo;
}

/**
 * История изменений статьи. Соответствует backend
 * `ArticleVersionResponse` (articles/schemas.py:112-130) —
 * router маппит `author_sub → author` для OpenAPI compat.
 */
export interface ArticleVersion {
  version: number;
  author: string;
  changed_at: string;
  event: string;
  changes_summary: string | null;
}

export interface ArticleHistoryResponse {
  data: ArticleVersion[];
}

/**
 * Search hit. Соответствует backend `SearchHit` (articles/schemas.py).
 * `type` — для E2.5a всегда 'article' (document/premises_card/regulation
 * — другие домены, появятся в kb-search эпике).
 * `snippet` может быть `null` если ts_headline не нашёл подходящий фрагмент.
 */
export interface SearchHit {
  type: string;
  id: string;
  title: string;
  snippet: string | null;
  score: number;
}

export interface ArticlesSearchResponse {
  data: SearchHit[];
  pagination: PaginationInfo;
}

// ============================================================================
// Categories

export interface Category {
  slug: string;
  title: string;
  description: string | null;
  article_count: number;
  children: Category[];
}

export interface CategoriesListResponse {
  data: Category[];
}

// ============================================================================
// Tags

export interface Tag {
  name: string;
  article_count: number;
}

export interface TagsListResponse {
  data: Tag[];
}

// ============================================================================
// Documents

export type DocumentCategory = "A" | "B" | "C" | "D" | "E" | "F";
export type DocumentStatus = "DRAFT" | "ACTIVE" | "EXPIRED" | "CANCELLED";
export type DocumentConfidentiality = "PUBLIC" | "INTERNAL" | "RESTRICTED";
export type DocumentFileFormat = "docx" | "pdf" | "html";

export interface DocumentFile {
  format: DocumentFileFormat;
  size_bytes: number;
  sha256: string;
}

export interface SignedBy {
  role: string;
  name: string;
  date: string;
  method: "sms_otp" | "qep" | "paper";
}

export interface AuditLogEntry {
  actor: string;
  action: string;
  ts: string;
}

export interface DocumentMeta {
  id: string;
  title: string;
  category: DocumentCategory;
  version: string | null;
  effective_from: string | null;
  effective_to: string | null;
  status: DocumentStatus;
  counterparty: string | null;
  confidentiality: DocumentConfidentiality;
  related_entity: string | null;
  files: DocumentFile[];
}

export interface Document extends DocumentMeta {
  signed_by: SignedBy[];
  audit_log: AuditLogEntry[];
}

export interface DocumentsListResponse {
  data: DocumentMeta[];
  pagination: PaginationInfo;
}

// ============================================================================
// Chat

export type ChatRole = "user" | "assistant" | "system";

export interface ChatSession {
  id: string;
  user_id: string | null;
  scope: string;
  context: Record<string, unknown>;
  created_at: string;
  expires_at: string;
}

/**
 * Citation для chat assistant message (#138).
 *
 * Соответствует backend `hits_to_citations` (chat/system_prompt.py).
 * Stage 1: только `type='article'`. `url` всегда относительный
 * (`/articles/{slug}`) — клиент navigate'ит в SPA-стиле.
 */
export interface Citation {
  type: "article";
  id: string;
  title: string;
  slug: string;
  chunk_index: number;
  score: number;
  url: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  citations: Citation[];
  feedback: { rating: "up" | "down"; comment?: string } | null;
  token_count: number | null;
  duration_ms: number | null;
  created_at: string;
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[];
}

export interface EscalateResponse {
  ticket_id: string;
  estimated_response_time_minutes: number;
}

// ============================================================================
// Webhooks (UI.7 #95)

/**
 * Allowed webhook events. Mirror backend `WebhookEvent` StrEnum
 * (webhooks/events.py) — source of truth.
 */
export const WEBHOOK_EVENTS = [
  "article.published",
  "article.updated",
  "article.archived",
  "document.created",
  "document.signed",
  "chat.escalated",
  "chat.no_answer",
  "search.popular_query",
  "premises_card.updated",
  "audit.security_event",
  "collaborator.created",
] as const;

export type WebhookEvent = (typeof WEBHOOK_EVENTS)[number];

/**
 * Webhook summary в list-response. БЕЗ `secret` — secret returned ТОЛЬКО
 * на POST 201 (creation), при последующих GET намеренно скрыт (#97).
 */
export interface WebhookSummary {
  id: string;
  client_id: string;
  url: string;
  events: string[];
  description: string | null;
  created_at: string;
  last_delivery_at: string | null;
  last_delivery_status: number | null;
}

/**
 * Webhook на creation-response (POST 201). Расширяет Summary полем `secret`.
 */
export interface Webhook extends WebhookSummary {
  secret: string;
}

export interface WebhooksListResponse {
  data: WebhookSummary[];
}

export interface WebhookInput {
  url: string;
  events: string[];
  description?: string | null;
}

export interface WebhookTestResponse {
  delivery_id: string;
  status: "enqueued";
}

// ============================================================================
// kb-hr (#153, PZ §7)

export type EmployeeStatus = "ACTIVE" | "ON_LEAVE" | "TERMINATED";

/** Brief view для list endpoint — без notes / contact_info (PII). */
export interface HrEmployeeSummary {
  id: string;
  full_name: string;
  position: string;
  department: string | null;
  hire_date: string;
  status: EmployeeStatus;
  updated_at: string;
}

/** Detail view — full employee record (HR_RESTRICTED). */
export interface HrEmployee extends HrEmployeeSummary {
  user_id: string | null;
  personnel_number: string | null;
  termination_date: string | null;
  contact_info: Record<string, unknown>;
  notes: Record<string, unknown>;
  created_at: string;
  archived_at: string | null;
}

export interface HrEmployeeListResponse {
  data: HrEmployeeSummary[];
  pagination: {
    cursor_next: string | null;
    has_more: boolean;
  };
}

// ============================================================================
// kb-premises (#160, PZ §5)

export type PremisesStatus = "DRAFT" | "PUBLISHED" | "RENTED" | "ARCHIVED";

/** Brief view для list — только identification (без PII / financial). */
export interface PremisesSummary {
  id: string;
  slug: string;
  status: PremisesStatus | string;
  address: string;
  postal_code: string | null;
  cadastral_number: string | null;
  updated_at: string;
}

/** Detail view с per-scope projection.
 *
 * Non-STAFF получают только identification subset (PII fields null/omitted).
 * STAFF tier видит все blocks.
 */
export interface PremisesView {
  id: string;
  slug: string;
  status: PremisesStatus | string;
  address: string;
  postal_code: string | null;
  cadastral_number: string | null;
  extra_identification: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  // STAFF-only fields (omit'аются в anon/tenant response).
  internal_code?: string | null;
  premises_uuid?: string | null;
  owner?: Record<string, unknown> | null;
  owner_representative?: Record<string, unknown> | null;
  current_tenant?: Record<string, unknown> | null;
  financial_data?: Record<string, unknown> | null;
  tenant_info?: Record<string, unknown> | null;
  internal_data?: Record<string, unknown> | null;
}

export interface PremisesListResponse {
  data: PremisesSummary[];
  pagination: {
    cursor_next: string | null;
    has_more: boolean;
  };
}

export interface PremisesSearchHit {
  id: string;
  slug: string;
  address: string;
  postal_code: string | null;
  cadastral_number: string | null;
  status: PremisesStatus | string;
  score: number;
}

export interface PremisesSearchResponse {
  data: PremisesSearchHit[];
}

// ============================================================================
// Audit log (#166, backend #161)

export interface AuditRecord {
  id: string;
  actor_sub: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AuditListResponse {
  data: AuditRecord[];
  pagination: { limit: number; offset: number; count: number };
}

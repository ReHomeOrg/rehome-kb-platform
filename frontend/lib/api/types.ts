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
  storage_key?: string | null;
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
 * `type="article"` — body chunk; `type="article_question"` —
 * ANSWERED Q&A (2026-05-29). `url` всегда относительный
 * (`/articles/{slug}` или с anchor'ом `#question-{id}` для Q&A) — клиент
 * navigate'ит в SPA-стиле.
 */
export interface Citation {
  type: "article" | "article_question";
  id: string;
  title: string;
  slug: string;
  chunk_index: number;
  score: number;
  url: string;
  /** Set только когда type="article_question". */
  question_id?: string;
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
  "collaborator.activated",
  "collaborator.suspended",
  "collaborator.archived",
  "collaborator.review.posted",
  "collaborator.portal_access.changed",
  "collaborator.onboarding.submitted",
  "service_order.created",
  "service_order.accepted",
  "service_order.completed",
  "service_order.cancelled",
  "service_order.failed",
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
// Collaborators (ADR-0014, ТЗ §10)

export type CollaboratorType =
  | "management_company"
  | "emergency_service"
  | "repair_handyman"
  | "cleaning"
  | "moving"
  | "key_delivery"
  | "insurance"
  | "payment_partner"
  | "kyc_provider"
  | "edo_provider"
  | "sms_voice"
  | "it_infrastructure"
  | "legal_consultant"
  | "other";

export type CollaboratorFinancialGroup = "A" | "B" | "C" | "D";

export type CollaboratorStatus =
  | "DRAFT"
  | "PENDING_REVIEW"
  | "ACTIVE"
  | "SUSPENDED"
  | "ARCHIVED";

export type CollaboratorLegalEntityType =
  | "individual"
  | "self_employed"
  | "ip"
  | "legal_entity";

export type CollaboratorOnboardingSource =
  | "form"
  | "staff_invite"
  | "api"
  | "migration";

export type CollaboratorPortalAccessLevel = "NONE" | "LIGHT" | "FULL";

export interface CollaboratorPublic {
  id: string;
  type: CollaboratorType;
  brand_name: string | null;
  financial_group: CollaboratorFinancialGroup;
  status: CollaboratorStatus;
  service_area: string;
  working_hours: string | null;
  website: string | null;
  rating: number | null;
}

export interface CollaboratorContact {
  phone: string | null;
  email: string | null;
  messenger: string | null;
  emergency_channel: boolean;
  person_name: string | null;
  person_role: string | null;
}

export interface CollaboratorInternal extends CollaboratorPublic {
  name: string;
  legal_entity_type: CollaboratorLegalEntityType | null;
  inn: string | null;
  ogrn: string | null;
  kpp: string | null;
  responsible_internal: string | null;
  contract_document_id: string | null;
  fallback_collaborator_id: string | null;
  contacts: CollaboratorContact[];
  financial_terms: Record<string, unknown>;
  api_integration: Record<string, unknown>;
  sla: Record<string, unknown>;
  counterparty_check: Record<string, unknown>;
  onboarding_source: CollaboratorOnboardingSource;
  portal_access_level: CollaboratorPortalAccessLevel;
  created_at: string;
  updated_at: string;
}

export interface CollaboratorAdmin extends CollaboratorInternal {
  audit_log: Array<Record<string, unknown>>;
}

export interface CollaboratorsListResponse {
  data: Array<CollaboratorPublic | CollaboratorInternal>;
  pagination: PaginationInfo;
}

/**
 * Junction row для `GET /api/v1/premises/{id}/collaborators` (ТЗ §10.6, Slice 5).
 * Inline-developed Collaborator card — Public variant (безопасно для anon).
 */
export interface PremisesCollaboratorRow {
  id: string;
  collaborator_id: string;
  role: string;
  priority: number;
  notes: string | null;
  assigned_at: string;
  assigned_by: string;
  collaborator: CollaboratorPublic;
}

export interface PremisesCollaboratorsListResponse {
  data: PremisesCollaboratorRow[];
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

// ============================================================================
// Admin eval-runs (#248, backend #244)

export type EvalRunStatus = "RUNNING" | "COMPLETED" | "FAILED";
export type EvalTestSet = "full" | "smoke" | "custom";

export interface EvalRunProviderResult {
  provider: string;
  composite_score: number | null;
  answer_correctness: number | null;
  faithfulness: number | null;
  citation_accuracy: number | null;
  refusal_correctness: number | null;
  avg_latency_ms: number | null;
  cost_per_query_rub: number | null;
}

export interface EvalRunSummary {
  id: string;
  started_at: string;
  completed_at: string | null;
  status: EvalRunStatus;
  providers: string[];
  test_set: string | null;
  results: EvalRunProviderResult[];
}

export interface EvalRunListResponse {
  data: EvalRunSummary[];
}

// ============================================================================
// Admin security incidents (#249, backend #231)

export type IncidentSeverity = "low" | "medium" | "high" | "critical";
export type IncidentStatus =
  | "OPEN"
  | "INVESTIGATING"
  | "RESOLVED"
  | "FALSE_POSITIVE";
export type IncidentDetectedBy =
  | "monitoring"
  | "audit"
  | "user_report"
  | "staff"
  | "automated_scan";

export interface SecurityIncident {
  id: string;
  incident_type: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  detected_at: string;
  detected_by: IncidentDetectedBy;
  affected_resources: Record<string, unknown>[];
  rkn_notification_required: boolean;
  rkn_notified_at: string | null;
  resolution_note: string | null;
  resolved_at: string | null;
}

export interface SecurityIncidentsListResponse {
  data: SecurityIncident[];
}

// ============================================================================
// Admin personal-data/requests (#250, backend #232) — ФЗ-152 §15 SAR

export type PdRequestType = "provide" | "correct" | "delete" | "transfer";
export type PdRequestStatus =
  | "NEW"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "REJECTED"
  | "OVERDUE";

export interface PersonalDataRequest {
  id: string;
  type: PdRequestType;
  status: PdRequestStatus;
  subject_id: string;
  subject_email: string | null;
  subject_phone: string | null;
  description: string | null;
  assigned_to: string | null;
  created_at: string;
  due_at: string;
  completed_at: string | null;
  resolution_note: string | null;
}

export interface PersonalDataRequestsListResponse {
  data: PersonalDataRequest[];
}

// ============================================================================
// Admin stats (#251, backend #227)

export interface AdminStatsPeriod {
  from: string;
  to: string;
}

export interface AdminStatsRequests {
  total: number;
  by_endpoint: Record<string, number>;
  by_status: Record<string, number>;
  error_rate_percent: number;
}

export interface AdminStatsChat {
  sessions: number;
  messages: number;
  containment_rate: number;
  avg_rating: number | null;
  no_answer_count: number;
  escalations: number;
}

export interface AdminStatsContent {
  total_articles: number;
  total_documents: number;
  pending_reviews: number;
}

export interface AdminStatsSecurity {
  open_incidents: number;
  critical_incidents: number;
  overdue_pd_requests: number;
}

export interface AdminStats {
  period: AdminStatsPeriod;
  requests: AdminStatsRequests;
  chat: AdminStatsChat;
  content: AdminStatsContent;
  security: AdminStatsSecurity;
}

// ============================================================================
// Admin LLM providers (#252, backend #228)

export type LlmProviderStatus = "ACTIVE" | "INACTIVE" | "EXPERIMENTAL";
export type LlmHealthStatus = "ok" | "degraded" | "down";

export interface LlmProvider {
  id: string;
  name: string;
  vendor: string | null;
  model: string | null;
  status: LlmProviderStatus;
  is_current: boolean;
  cost_per_1m_input_tokens_rub: number | null;
  cost_per_1m_output_tokens_rub: number | null;
  max_context_tokens: number | null;
  supports_streaming: boolean | null;
  last_health_check: string | null;
  health_status: LlmHealthStatus | null;
}

export interface LlmProvidersListResponse {
  data: LlmProvider[];
}

// ============================================================================
// Admin system config (#252, backend #229)

export interface SystemConfigRateLimits {
  guest_per_minute: number | null;
  user_per_minute: number | null;
  m2m_per_minute: number | null;
  chat_messages_per_5min: number | null;
}

export interface SystemConfigLlm {
  active_provider: string;
  fallback_provider: string | null;
  ab_test_split_percent: number | null;
  max_context_tokens: number | null;
  temperature: number | null;
}

export interface SystemConfigModeration {
  auto_publish_threshold: number | null;
  require_review_for_categories: string[];
}

export interface SystemConfigWebhooks {
  max_retries: number;
  timeout_seconds: number;
}

export interface SystemConfig {
  rate_limits: SystemConfigRateLimits;
  feature_flags: Record<string, boolean>;
  llm_config: SystemConfigLlm;
  moderation: SystemConfigModeration;
  webhooks: SystemConfigWebhooks;
}

// ============================================================================
// Admin KB users (#253, backend #230)

export type KbUserRole = "staff_support" | "staff_legal" | "staff_hr" | "staff_admin";
export type KbUserStatus = "ACTIVE" | "SUSPENDED" | "ARCHIVED";

export interface KbUser {
  id: string;
  email: string;
  full_name: string;
  role: KbUserRole;
  permissions: string[];
  status: KbUserStatus;
  created_at: string;
  last_login_at: string | null;
  mfa_enabled: boolean;
}

export interface KbUsersListResponse {
  data: KbUser[];
}

// ============================================================================
// Admin tasks (#262, backend #238)

export type AdminTaskStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";
export type AdminTaskType =
  | "reindex"
  | "audit_log_export"
  | "cache_invalidation"
  | "eval_run";

export interface AdminTaskStatusView {
  task_id: string;
  type: AdminTaskType;
  status: AdminTaskStatus;
  progress_percent: number;
  created_at: string;
  completed_at: string | null;
  result_url: string | null;
  error: string | null;
}

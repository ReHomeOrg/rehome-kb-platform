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

export interface ArticleSummary {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  category: string;
  audience: string;
  language: string;
  tags: string[];
  access_level: string;
  status: string;
  published_at: string | null;
  updated_at: string;
}

export interface Article extends ArticleSummary {
  body_markdown: string;
  created_at: string;
}

export interface ArticlesListResponse {
  data: ArticleSummary[];
  pagination: PaginationInfo;
}

export interface ArticleVersion {
  version: number;
  event: string;
  author_sub: string;
  changed_at: string;
  old_status: string | null;
  new_status: string;
  old_access_level: string | null;
  new_access_level: string;
  changes_summary: string | null;
}

export interface ArticleHistoryResponse {
  data: ArticleVersion[];
}

export interface SearchHit {
  id: string;
  title: string;
  snippet: string;
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

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  citations: Array<Record<string, unknown>>;
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

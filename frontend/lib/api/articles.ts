/**
 * Articles API methods (UI.1 #75) — typed wrappers around `apiFetch`.
 *
 * Maps to backend `/api/v1/articles/*` endpoints (E2.1-E2.5, E4.1-E4.5).
 */

import { apiFetch } from "./client";
import type {
  Article,
  ArticleHistoryResponse,
  ArticlesListResponse,
  ArticlesSearchResponse,
} from "./types";

export interface ListArticlesFilters {
  category?: string;
  audience?: string;
  language?: string;
  tags?: string;
  cursor?: string;
  limit?: number;
}

export async function listArticles(
  filters: ListArticlesFilters = {},
): Promise<ArticlesListResponse> {
  const params = new URLSearchParams();
  if (filters.category) params.set("category", filters.category);
  if (filters.audience) params.set("audience", filters.audience);
  if (filters.language) params.set("language", filters.language);
  if (filters.tags) params.set("tags", filters.tags);
  if (filters.cursor) params.set("cursor", filters.cursor);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return apiFetch<ArticlesListResponse>(
    `/api/v1/articles${qs ? `?${qs}` : ""}`,
  );
}

export async function getArticle(slug: string): Promise<Article> {
  return apiFetch<Article>(`/api/v1/articles/${encodeURIComponent(slug)}`);
}

export async function getArticleHistory(
  slug: string,
): Promise<ArticleHistoryResponse> {
  return apiFetch<ArticleHistoryResponse>(
    `/api/v1/articles/${encodeURIComponent(slug)}/history`,
  );
}

export interface SearchArticlesInput {
  q: string;
  cursor?: string;
  limit?: number;
}

export async function searchArticles(
  input: SearchArticlesInput,
): Promise<ArticlesSearchResponse> {
  return apiFetch<ArticlesSearchResponse>("/api/v1/articles/search", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

// ---------------------------------------------------------------------------
// Write side — STAFF+ (backend enforce'ит require_access_level(STAFF) +
// ensure_can_write_access_level для writer extension per ADR-0003).

export type ArticleAccessLevel =
  | "PUBLIC"
  | "LOGGED"
  | "AGENT"
  | "STAFF"
  | "LEGAL"
  | "HR_RESTRICTED";

export interface ArticleCreateInput {
  slug: string;
  title: string;
  body_markdown: string;
  category: string;
  audience: string;
  access_level: ArticleAccessLevel;
  status?: string;
  language?: string;
  tags?: string[];
}

/** PATCH only: backend `ArticlePatch` запрещает менять slug / category /
 * access_level / audience / language через PATCH (extra='forbid'). Это
 * security-by-design: writer не может тихо повысить visibility. Для смены
 * этих полей нужен PUT (replace), отдельный flow если потребуется. */
export interface ArticlePatchInput {
  title?: string;
  body_markdown?: string;
  tags?: string[];
  status?: string;
}

export async function createArticle(
  input: ArticleCreateInput,
): Promise<Article> {
  return apiFetch<Article>("/api/v1/articles", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function patchArticle(
  slug: string,
  input: ArticlePatchInput,
): Promise<Article> {
  return apiFetch<Article>(`/api/v1/articles/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Article Q&A (ТЗ §2, 2026-05-28)

export type ArticleQuestionStatus = "PENDING" | "ANSWERED" | "DISMISSED";

/** Public view — без `author_sub` (privacy). */
export interface ArticleQuestionPublic {
  id: string;
  body: string;
  answer_body: string;
  answered_at: string;
  created_at: string;
}

export interface ArticleQuestionPublicListResponse {
  data: ArticleQuestionPublic[];
}

/** Admin view — все поля. */
export interface ArticleQuestionAdmin {
  id: string;
  article_id: string;
  author_sub: string;
  body: string;
  status: ArticleQuestionStatus;
  answer_body: string | null;
  answerer_sub: string | null;
  dismiss_reason: string | null;
  created_at: string;
  answered_at: string | null;
  updated_at: string;
}

export interface ArticleQuestionAdminListResponse {
  data: ArticleQuestionAdmin[];
  total: number;
}

export async function listArticleQuestions(
  slug: string,
): Promise<ArticleQuestionPublicListResponse> {
  return apiFetch<ArticleQuestionPublicListResponse>(
    `/api/v1/articles/${encodeURIComponent(slug)}/questions`,
  );
}

export async function submitArticleQuestion(
  slug: string,
  body: string,
): Promise<ArticleQuestionAdmin> {
  return apiFetch<ArticleQuestionAdmin>(
    `/api/v1/articles/${encodeURIComponent(slug)}/questions`,
    {
      method: "POST",
      body: JSON.stringify({ body }),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function listAdminArticleQuestions(
  params: {
    status?: ArticleQuestionStatus;
    limit?: number;
    offset?: number;
  } = {},
): Promise<ArticleQuestionAdminListResponse> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const tail = qs.toString();
  return apiFetch<ArticleQuestionAdminListResponse>(
    `/api/v1/admin/article-questions${tail ? `?${tail}` : ""}`,
  );
}

export async function answerArticleQuestion(
  questionId: string,
  answerBody: string,
): Promise<ArticleQuestionAdmin> {
  return apiFetch<ArticleQuestionAdmin>(
    `/api/v1/admin/article-questions/${encodeURIComponent(questionId)}/answer`,
    {
      method: "POST",
      body: JSON.stringify({ answer_body: answerBody }),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function dismissArticleQuestion(
  questionId: string,
  reason: string | null,
): Promise<ArticleQuestionAdmin> {
  return apiFetch<ArticleQuestionAdmin>(
    `/api/v1/admin/article-questions/${encodeURIComponent(questionId)}/dismiss`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
      headers: { "Content-Type": "application/json" },
    },
  );
}

// ---------------------------------------------------------------------------

export async function deleteArticle(slug: string): Promise<void> {
  await apiFetch<void>(`/api/v1/articles/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
}

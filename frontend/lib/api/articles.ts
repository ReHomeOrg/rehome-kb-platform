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

export async function deleteArticle(slug: string): Promise<void> {
  await apiFetch<void>(`/api/v1/articles/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
}

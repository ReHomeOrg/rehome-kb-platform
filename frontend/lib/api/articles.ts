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

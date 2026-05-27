/**
 * Admin analytics dashboard (2026-05-28).
 *
 * Surfaces aggregate KB usage:
 * - Top search queries в window (с content-gap breakdown).
 * - Per-article Q&A counts (PENDING/ANSWERED/DISMISSED).
 */

import { apiFetch } from "./client";

export interface TopQuery {
  query: string;
  total: number;
  with_results: number;
  without_results: number;
}

export interface TopQueriesResponse {
  window_hours: number;
  data: TopQuery[];
}

export interface ArticleQuestionsCount {
  article_id: string;
  slug: string;
  title: string;
  pending: number;
  answered: number;
  dismissed: number;
  total: number;
}

export interface ArticleQuestionsCountResponse {
  data: ArticleQuestionsCount[];
}

export async function getTopQueries(
  params: { windowHours?: number; limit?: number } = {},
): Promise<TopQueriesResponse> {
  const qs = new URLSearchParams();
  if (params.windowHours !== undefined)
    qs.set("window_hours", String(params.windowHours));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const tail = qs.toString();
  return apiFetch<TopQueriesResponse>(
    `/api/v1/admin/analytics/queries${tail ? `?${tail}` : ""}`,
  );
}

export async function getArticleQuestionsCounts(
  params: { limit?: number } = {},
): Promise<ArticleQuestionsCountResponse> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const tail = qs.toString();
  return apiFetch<ArticleQuestionsCountResponse>(
    `/api/v1/admin/analytics/article-questions${tail ? `?${tail}` : ""}`,
  );
}

/**
 * Admin analytics dashboard (2026-05-28).
 *
 * Surfaces aggregate KB usage:
 * - Top search queries в window (с content-gap breakdown).
 * - Per-article Q&A counts (PENDING/ANSWERED/DISMISSED).
 * - Top unanswered chat queries (trend buckets) — moderation
 *   prioritization сверх #350 capture queue.
 */

import { apiFetch } from "./client";

export type UnansweredStatus = "NEW" | "ATTACHED" | "DISMISSED";

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

export interface UnansweredTrend {
  normalized_query: string;
  count: number;
  first_seen: string;
  last_seen: string;
}

export interface UnansweredTrendResponse {
  window_hours: number;
  status: UnansweredStatus;
  data: UnansweredTrend[];
}

export async function getTopUnansweredQueries(
  params: {
    windowHours?: number;
    limit?: number;
    status?: UnansweredStatus;
  } = {},
): Promise<UnansweredTrendResponse> {
  const qs = new URLSearchParams();
  if (params.windowHours !== undefined)
    qs.set("window_hours", String(params.windowHours));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.status !== undefined) qs.set("status", params.status);
  const tail = qs.toString();
  return apiFetch<UnansweredTrendResponse>(
    `/api/v1/admin/analytics/unanswered-queries${tail ? `?${tail}` : ""}`,
  );
}

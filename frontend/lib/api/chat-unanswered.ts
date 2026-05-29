/**
 * /api/v1/admin/chat-unanswered-queries — admin moderation queue для chat
 * queries без RAG hits (2026-05-29).
 *
 * Backend: backend/src/api/chat/unanswered_router.py.
 */

import { apiFetch } from "@/lib/api/client";
import type { ArticleQuestionAdmin } from "@/lib/api/articles";

export type ChatUnansweredStatus = "NEW" | "ATTACHED" | "DISMISSED";

export interface ChatUnansweredQuery {
  id: string;
  query_masked: string;
  author_sub: string;
  chat_session_id: string | null;
  status: ChatUnansweredStatus;
  attached_question_id: string | null;
  attached_article_slug: string | null;
  dismiss_reason: string | null;
  created_at: string;
  attached_at: string | null;
  updated_at: string;
}

export interface ChatUnansweredListResponse {
  data: ChatUnansweredQuery[];
  total: number;
}

export interface ChatUnansweredAttachResponse {
  unanswered: ChatUnansweredQuery;
  question: ArticleQuestionAdmin;
}

export async function listChatUnansweredQueries(
  params: {
    status?: ChatUnansweredStatus;
    limit?: number;
    offset?: number;
  } = {},
): Promise<ChatUnansweredListResponse> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const tail = qs.toString();
  return apiFetch<ChatUnansweredListResponse>(
    `/api/v1/admin/chat-unanswered-queries${tail ? `?${tail}` : ""}`,
  );
}

export async function attachChatUnansweredQuery(
  id: string,
  payload: { article_slug: string; question_body?: string | null },
): Promise<ChatUnansweredAttachResponse> {
  return apiFetch<ChatUnansweredAttachResponse>(
    `/api/v1/admin/chat-unanswered-queries/${encodeURIComponent(id)}/attach`,
    {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function dismissChatUnansweredQuery(
  id: string,
  reason: string | null,
): Promise<ChatUnansweredQuery> {
  return apiFetch<ChatUnansweredQuery>(
    `/api/v1/admin/chat-unanswered-queries/${encodeURIComponent(id)}/dismiss`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
      headers: { "Content-Type": "application/json" },
    },
  );
}

/**
 * Chat API methods (UI.1 #75) — typed wrappers.
 *
 * Maps to backend `/api/v1/chat/*` (E3.1-E3.7).
 *
 * **X-Chat-Session-Token**: для анонимных sessions backend выдаёт
 * opaque token в response header при `POST /sessions`. Client должен
 * хранить его (localStorage / cookie) и слать в последующих
 * GET/POST. JS не имеет доступа к HttpOnly `kb_session`, поэтому
 * для chat session_token хранится в обычной cookie (UI-level, не PII).
 *
 * **SSE**: для streaming используется отдельный proxy `/api/kb-sse/...`
 * через `fetch` + ReadableStream (не EventSource, который не поддерживает
 * custom headers). Caller parsят stream через `parseSseStream`.
 */

import { apiFetch } from "./client";
import type {
  ChatMessage,
  ChatSession,
  ChatSessionDetail,
  EscalateResponse,
} from "./types";

export interface ChatContext {
  page_url?: string;
  premises_id?: string;
  booking_id?: string;
}

export interface CreateSessionInput {
  context?: ChatContext;
}

/**
 * Возвращает session + опциональный session_token (если backend выдал
 * для анонимного flow). Client обязан сохранить token и слать в
 * последующих запросах через `X-Chat-Session-Token` header.
 */
export interface CreateSessionResult {
  session: ChatSession;
  sessionToken: string | null;
}

export async function createSession(
  input?: CreateSessionInput,
): Promise<CreateSessionResult> {
  // apiFetch не отдаёт raw Response — нам нужен header. Делаем fetch напрямую.
  // Reuse buildUrl/buildHeaders логику через дублирование (минимально).
  const isServer = typeof window === "undefined";
  const url = isServer
    ? `${(await import("@/lib/env")).getBackendBaseUrl()}/api/v1/chat/sessions`
    : "/api/kb/api/v1/chat/sessions";
  const headers = new Headers({ "Content-Type": "application/json" });
  if (isServer) {
    const { cookies } = await import("next/headers");
    const { COOKIE_SESSION } = await import("@/lib/auth/cookies");
    const session = (await cookies()).get(COOKIE_SESSION)?.value;
    if (session) headers.set("Authorization", `Bearer ${session}`);
  }
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(input ?? {}),
  });
  if (!response.ok) {
    const { ApiError } = await import("./client");
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, body);
  }
  const sessionToken = response.headers.get("X-Chat-Session-Token");
  const sessionPayload = (await response.json()) as ChatSession;
  return { session: sessionPayload, sessionToken };
}

export interface ChatRequestHeaders {
  sessionToken?: string | null;
}

function chatHeaders(opts?: ChatRequestHeaders): HeadersInit {
  if (opts?.sessionToken) {
    return { "X-Chat-Session-Token": opts.sessionToken };
  }
  return {};
}

export async function getSession(
  sessionId: string,
  opts?: ChatRequestHeaders,
): Promise<ChatSessionDetail> {
  return apiFetch<ChatSessionDetail>(
    `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`,
    { headers: chatHeaders(opts) },
  );
}

export async function deleteSession(
  sessionId: string,
  opts?: ChatRequestHeaders,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE", headers: chatHeaders(opts) },
  );
}

export interface SendMessageInput {
  content: string;
}

export async function sendMessageJson(
  sessionId: string,
  input: SendMessageInput,
  opts?: ChatRequestHeaders,
): Promise<ChatMessage> {
  return apiFetch<ChatMessage>(
    `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      headers: {
        ...chatHeaders(opts),
        Accept: "application/json",
      },
      body: JSON.stringify(input),
    },
  );
}

export interface FeedbackInput {
  message_id: string;
  rating: "up" | "down";
  comment?: string;
}

export async function postFeedback(
  sessionId: string,
  input: FeedbackInput,
  opts?: ChatRequestHeaders,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/feedback`,
    {
      method: "POST",
      headers: chatHeaders(opts),
      body: JSON.stringify(input),
    },
  );
}

export interface EscalateInput {
  reason?: string;
  priority?: "low" | "normal" | "high";
}

export async function escalate(
  sessionId: string,
  input?: EscalateInput,
  opts?: ChatRequestHeaders,
): Promise<EscalateResponse> {
  return apiFetch<EscalateResponse>(
    `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/escalate`,
    {
      method: "POST",
      headers: chatHeaders(opts),
      body: JSON.stringify(input ?? {}),
    },
  );
}

// ============================================================================
// SSE streaming

export interface SseEvent {
  event: string;
  data: unknown;
}

/**
 * Stream messages через SSE proxy `/api/kb-sse/...`.
 *
 * Используется `fetch` + ReadableStream вместо EventSource — нужны
 * custom headers (X-Chat-Session-Token). Streamer возвращает
 * AsyncIterator<SseEvent> с распарсенными events.
 *
 * Caller pattern:
 * ```typescript
 * for await (const ev of streamMessage(sessionId, input, { sessionToken })) {
 *   if (ev.event === 'chunk') ...
 * }
 * ```
 */
export async function* streamMessage(
  sessionId: string,
  input: SendMessageInput,
  opts?: ChatRequestHeaders,
): AsyncIterableIterator<SseEvent> {
  const url = `/api/kb-sse/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/messages`;
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
    ...chatHeaders(opts),
  };
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(input),
  });
  if (!response.ok || !response.body) {
    const { ApiError } = await import("./client");
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, body);
  }
  yield* parseSseStream(response.body);
}

async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
): AsyncIterableIterator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE events разделены `\n\n`.
    let separatorIndex = buffer.indexOf("\n\n");
    while (separatorIndex !== -1) {
      const block = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      const event = parseSseBlock(block);
      if (event) yield event;
      separatorIndex = buffer.indexOf("\n\n");
    }
  }
}

function parseSseBlock(block: string): SseEvent | null {
  let event = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice("event: ".length);
    else if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (!event) return null;
  try {
    return { event, data: JSON.parse(data) };
  } catch {
    return { event, data };
  }
}

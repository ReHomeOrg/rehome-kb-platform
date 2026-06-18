"use client";

/**
 * Message thread с SSE consume (UI.4 #81) — core chat component.
 *
 * Загружает session detail при mount, держит local state messages.
 * Submit → POST /messages с Accept SSE → streamMessage iterator →
 * append chunks к "pending" assistant message → final message-end
 * обновляет id + content + token_count.
 *
 * Empty session — placeholder. 404 → not found page (через redirect).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { getSession, streamMessage } from "@/lib/api/chat";
import { ApiError } from "@/lib/api/client";
import type { ChatMessage, Citation } from "@/lib/api/types";

import CitationsBlock from "./citations-block";
import EscalateButton from "./escalate-button";
import FeedbackButtons from "./feedback-buttons";
import MessageInput from "./message-input";

interface MessageThreadProps {
  sessionId: string;
  sessionToken: string | null;
}

interface StreamEvent {
  event: string;
  data: unknown;
}

function isMessageEnd(
  data: unknown,
): data is { message_id: string; total_tokens?: number } {
  if (typeof data !== "object" || data === null) return false;
  const obj = data as Record<string, unknown>;
  return typeof obj.message_id === "string";
}

function isChunkText(data: unknown): data is { text: string } {
  if (typeof data !== "object" || data === null) return false;
  return typeof (data as Record<string, unknown>).text === "string";
}

function isCitationsPayload(data: unknown): data is { data: unknown[] } {
  if (typeof data !== "object" || data === null) return false;
  return Array.isArray((data as Record<string, unknown>).data);
}

function isCitation(value: unknown): value is Citation {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    v.type === "article" &&
    typeof v.id === "string" &&
    typeof v.title === "string" &&
    typeof v.slug === "string" &&
    typeof v.chunk_index === "number" &&
    typeof v.score === "number" &&
    typeof v.url === "string"
  );
}

export default function MessageThread({
  sessionId,
  sessionToken,
}: MessageThreadProps): JSX.Element {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingAssistant, setPendingAssistant] = useState<string | null>(null);
  const [pendingCitations, setPendingCitations] = useState<Citation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const detail = await getSession(sessionId, { sessionToken });
        if (!cancelled) {
          setMessages(detail.messages);
          setLoaded(true);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          router.push(`/chat/${sessionId}/not-found`);
          return;
        }
        setError("Не удалось загрузить сессию");
        setLoaded(true);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [sessionId, sessionToken, router]);

  async function onSend(content: string): Promise<void> {
    // Optimistic user message в local state.
    const userMessage: ChatMessage = {
      id: `pending-user-${Date.now()}`,
      role: "user",
      content,
      citations: [],
      feedback: null,
      token_count: null,
      duration_ms: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setPendingAssistant("");
    setPendingCitations([]);
    setError(null);

    try {
      const iterator = streamMessage(
        sessionId,
        { content },
        { sessionToken },
      );
      let accumulated = "";
      let messageEnd: { message_id: string; total_tokens?: number } | null =
        null;
      let citations: Citation[] = [];
      for await (const ev of iterator as AsyncIterableIterator<StreamEvent>) {
        if (ev.event === "chunk" && isChunkText(ev.data)) {
          accumulated += ev.data.text;
          setPendingAssistant(accumulated);
        } else if (ev.event === "citations" && isCitationsPayload(ev.data)) {
          citations = ev.data.data.filter(isCitation);
          setPendingCitations(citations);
        } else if (ev.event === "message-end" && isMessageEnd(ev.data)) {
          messageEnd = ev.data;
        } else if (ev.event === "error") {
          throw new Error("LLM error event");
        }
      }
      if (messageEnd) {
        const finalMessage: ChatMessage = {
          id: messageEnd.message_id,
          role: "assistant",
          content: accumulated,
          citations,
          feedback: null,
          token_count: messageEnd.total_tokens ?? null,
          duration_ms: null,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, finalMessage]);
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? `Ошибка: ${err.message}`
          : "Не удалось получить ответ",
      );
      // Rollback optimistic user message — backend ничего не записал
      // при LLM exception (retry-safety E3.4).
      setMessages((prev) => prev.filter((m) => m.id !== userMessage.id));
    } finally {
      setPendingAssistant(null);
      setPendingCitations([]);
    }
  }

  if (!loaded) {
    return <p className="text-sm text-gray-500">Загрузка сессии…</p>;
  }

  if (error && messages.length === 0) {
    return (
      <p className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-700">
        {error}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-3">
        {messages.length === 0 && pendingAssistant === null ? (
          <li className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
            Начните диалог — задайте вопрос ниже.
          </li>
        ) : null}
        {messages.map((m) => (
          <li
            key={m.id}
            className={`rounded-md border p-3 ${
              m.role === "user"
                ? "border-mint bg-mint-soft"
                : "border-gray-200 bg-white"
            }`}
          >
            <header className="flex items-center justify-between text-xs text-gray-500">
              <span>{m.role === "user" ? "Вы" : "Ассистент"}</span>
              {m.role === "assistant" ? (
                <FeedbackButtons
                  sessionId={sessionId}
                  messageId={m.id}
                  sessionToken={sessionToken}
                  initial={m.feedback?.rating ?? null}
                />
              ) : null}
            </header>
            <p className="mt-1 whitespace-pre-wrap text-sm text-gray-900">
              {m.content}
            </p>
            {m.role === "assistant" ? (
              <CitationsBlock citations={m.citations} />
            ) : null}
          </li>
        ))}
        {pendingAssistant !== null ? (
          <li className="rounded-md border border-gray-200 bg-white p-3">
            <header className="text-xs text-gray-500">
              Ассистент <span className="animate-pulse">…</span>
            </header>
            <p className="mt-1 whitespace-pre-wrap text-sm text-gray-900">
              {pendingAssistant}
            </p>
            <CitationsBlock citations={pendingCitations} />
          </li>
        ) : null}
      </ul>
      {error && messages.length > 0 ? (
        <p className="text-sm text-red-600">{error}</p>
      ) : null}
      <MessageInput onSend={onSend} disabled={pendingAssistant !== null} />
      <EscalateButton sessionId={sessionId} sessionToken={sessionToken} />
    </div>
  );
}

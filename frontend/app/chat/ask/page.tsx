"use client";

/**
 * /chat/ask?q=… — точка входа из строки поиска главной: создаёт анонимную
 * chat-сессию, задаёт вопрос ассистенту и редиректит на тред с ответом.
 * Позволяет «спросил в поиске → получил ответ ИИ», не открывая чат вручную.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { createSession, sendMessageJson } from "@/lib/api/chat";
import { addRecentSession, setSessionToken } from "@/lib/chat-storage";

export default function ChatAskPage(): JSX.Element {
  const router = useRouter();
  const params = useSearchParams();
  const started = useRef(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const question = (params.get("q") ?? "").trim();
    async function run(): Promise<void> {
      try {
        const { session, sessionToken } = await createSession();
        if (sessionToken) setSessionToken(session.id, sessionToken);
        addRecentSession({
          id: session.id,
          created_at: session.created_at,
          scope: session.scope,
        });
        if (question) {
          await sendMessageJson(session.id, { content: question }, { sessionToken });
        }
        router.replace(`/chat/${session.id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось открыть чат");
      }
    }
    void run();
  }, [params, router]);

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      {error ? (
        <p className="text-sm text-red-600">{error}</p>
      ) : (
        <p className="text-sm text-gray-600">Ассистент готовит ответ…</p>
      )}
    </main>
  );
}

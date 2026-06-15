"use client";

/**
 * /chat/[session_id] — chat thread (UI.4 #81).
 *
 * Client Component (SSE consume + localStorage token чтение).
 */

import { useEffect, useState } from "react";

import MessageThread from "../_components/message-thread";
import { getSessionToken } from "@/lib/chat-storage";

interface PageProps {
  params: { session_id: string };
}

export default function ChatThreadPage({ params }: PageProps): JSX.Element {
  // Next 14 / React 18: в Client Component `params` — обычный объект (НЕ
  // Promise), читаем напрямую. `use(params)` бросил бы на не-thenable
  // ("An unsupported type was passed to use()") → error boundary.
  const { session_id } = params;
  const [token, setToken] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setToken(getSessionToken(session_id));
    setHydrated(true);
  }, [session_id]);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          Сессия {session_id.slice(0, 8)}…
        </h1>
        <p className="mt-1 text-xs text-gray-500">
          {token ? "Анонимный чат" : "Без токена — может не открыться"}
        </p>
      </header>
      {hydrated ? (
        <MessageThread sessionId={session_id} sessionToken={token} />
      ) : (
        <p className="text-sm text-gray-500">Инициализация…</p>
      )}
    </main>
  );
}

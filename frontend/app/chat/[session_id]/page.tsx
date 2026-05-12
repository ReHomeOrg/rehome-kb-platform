"use client";

/**
 * /chat/[session_id] — chat thread (UI.4 #81).
 *
 * Client Component (SSE consume + localStorage token чтение).
 */

import { use, useEffect, useState } from "react";

import Nav from "@/app/_components/nav";

import MessageThread from "../_components/message-thread";
import { getSessionToken } from "@/lib/chat-storage";

interface PageProps {
  params: Promise<{ session_id: string }>;
}

export default function ChatThreadPage({ params }: PageProps): JSX.Element {
  // React 19 hook `use()` для unwrap Promise params в Client Component.
  const { session_id } = use(params);
  const [token, setToken] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setToken(getSessionToken(session_id));
    setHydrated(true);
  }, [session_id]);

  return (
    <>
      <Nav />
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
    </>
  );
}

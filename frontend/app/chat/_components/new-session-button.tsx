"use client";

/**
 * Button — создаёт новую chat session, сохраняет token, redirects.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createSession } from "@/lib/api/chat";
import { addRecentSession, setSessionToken } from "@/lib/chat-storage";

export default function NewSessionButton(): JSX.Element {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick(): Promise<void> {
    setPending(true);
    setError(null);
    try {
      const { session, sessionToken } = await createSession();
      if (sessionToken) {
        setSessionToken(session.id, sessionToken);
      }
      addRecentSession({
        id: session.id,
        created_at: session.created_at,
        scope: session.scope,
      });
      router.push(`/chat/${session.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать сессию");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={pending}
        className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
      >
        {pending ? "Создаём…" : "Новая сессия"}
      </button>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </div>
  );
}

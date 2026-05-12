"use client";

/**
 * Escalate button (UI.4 #81) — POST /escalate, показывает ticket_id.
 */

import { useState } from "react";

import { escalate } from "@/lib/api/chat";

interface EscalateButtonProps {
  sessionId: string;
  sessionToken: string | null;
}

export default function EscalateButton({
  sessionId,
  sessionToken,
}: EscalateButtonProps): JSX.Element {
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<{
    ticket_id: string;
    estimated_response_time_minutes: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onClick(): Promise<void> {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const response = await escalate(
        sessionId,
        { priority: "normal" },
        { sessionToken },
      );
      setResult(response);
    } catch {
      setError("Не удалось эскалировать. Попробуйте позже.");
    } finally {
      setPending(false);
    }
  }

  if (result) {
    return (
      <div className="rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-800">
        Тикет создан: <code>{result.ticket_id.slice(0, 8)}…</code>. Оператор
        ответит в течение ~{result.estimated_response_time_minutes} мин.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={pending}
        className="rounded-md border border-gray-300 px-4 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
      >
        {pending ? "Эскалация…" : "Эскалировать на оператора"}
      </button>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </div>
  );
}

"use client";

/**
 * Feedback buttons (👍/👎) на assistant message (UI.4 #81).
 */

import { useState } from "react";

import { postFeedback } from "@/lib/api/chat";

interface FeedbackButtonsProps {
  sessionId: string;
  messageId: string;
  sessionToken: string | null;
  initial: "up" | "down" | null;
}

export default function FeedbackButtons({
  sessionId,
  messageId,
  sessionToken,
  initial,
}: FeedbackButtonsProps): JSX.Element {
  const [rating, setRating] = useState<"up" | "down" | null>(initial);
  const [pending, setPending] = useState(false);

  async function send(value: "up" | "down"): Promise<void> {
    if (pending) return;
    setPending(true);
    try {
      await postFeedback(
        sessionId,
        { message_id: messageId, rating: value },
        { sessionToken },
      );
      setRating(value);
    } catch {
      // tacit fail — user может retry. backlog: toast.
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex gap-1 text-sm">
      <button
        type="button"
        onClick={() => send("up")}
        disabled={pending}
        aria-label="Полезный ответ"
        className={`rounded px-2 py-0.5 ${
          rating === "up"
            ? "bg-green-100 text-green-700"
            : "text-gray-500 hover:bg-gray-100"
        }`}
      >
        👍
      </button>
      <button
        type="button"
        onClick={() => send("down")}
        disabled={pending}
        aria-label="Неполезный ответ"
        className={`rounded px-2 py-0.5 ${
          rating === "down"
            ? "bg-red-100 text-red-700"
            : "text-gray-500 hover:bg-gray-100"
        }`}
      >
        👎
      </button>
    </div>
  );
}

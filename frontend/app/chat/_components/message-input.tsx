"use client";

/**
 * Message input form (UI.4 #81).
 *
 * Submit вызывает onSend callback (parent thread обрабатывает SSE).
 * Локальный state — input value + pending flag.
 */

import { type FormEvent, useState } from "react";

interface MessageInputProps {
  onSend: (content: string) => Promise<void>;
  disabled?: boolean;
}

export default function MessageInput({
  onSend,
  disabled = false,
}: MessageInputProps): JSX.Element {
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    const trimmed = content.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    try {
      await onSend(trimmed);
      setContent("");
    } finally {
      setSubmitting(false);
    }
  }

  const blocked = disabled || submitting;

  return (
    <form onSubmit={onSubmit} className="flex gap-2">
      <input
        type="text"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Ваш вопрос…"
        maxLength={2000}
        disabled={blocked}
        className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900 disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={blocked || !content.trim()}
        className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-ink hover:bg-brand-hover disabled:opacity-50"
      >
        Отправить
      </button>
    </form>
  );
}

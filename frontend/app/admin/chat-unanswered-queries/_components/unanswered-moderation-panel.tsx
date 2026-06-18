"use client";

/**
 * Moderation panel для /admin/chat-unanswered-queries (2026-05-29).
 *
 * Per-row actions:
 * - NEW → attach (article slug + optional question_body override) либо
 *   dismiss (с optional reason).
 * - ATTACHED → read-only с link на созданный article_question.
 * - DISMISSED → read-only.
 */

import Link from "next/link";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  attachChatUnansweredQuery,
  dismissChatUnansweredQuery,
  type ChatUnansweredQuery,
  type ChatUnansweredStatus,
} from "@/lib/api/chat-unanswered";

interface Props {
  initialItems: ChatUnansweredQuery[];
  initialTotal: number;
  statusFilter: ChatUnansweredStatus;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown } | null;
    if (typeof body?.detail === "string") {
      return `${err.status}: ${body.detail}`;
    }
    return `${err.status}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Ошибка";
}

function StatusFilterTabs({
  current,
}: {
  current: ChatUnansweredStatus;
}): JSX.Element {
  const tabs: { value: ChatUnansweredStatus; label: string }[] = [
    { value: "NEW", label: "Новые" },
    { value: "ATTACHED", label: "Привязанные" },
    { value: "DISMISSED", label: "Отклонённые" },
  ];
  return (
    <nav className="flex gap-2 border-b border-gray-200">
      {tabs.map((t) => {
        const active = t.value === current;
        return (
          <Link
            key={t.value}
            href={`/admin/chat-unanswered-queries?status=${t.value}`}
            className={`px-3 py-1.5 text-sm ${
              active
                ? "border-b-2 border-gray-900 font-medium text-gray-900"
                : "text-gray-600 hover:text-gray-900"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}

function UnansweredRow({
  row,
  onUpdated,
}: {
  row: ChatUnansweredQuery;
  onUpdated: (updated: ChatUnansweredQuery) => void;
}): JSX.Element {
  const [articleSlug, setArticleSlug] = useState("");
  const [questionBody, setQuestionBody] = useState("");
  const [dismissReason, setDismissReason] = useState("");
  const [busy, setBusy] = useState<"attach" | "dismiss" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onAttach(): Promise<void> {
    if (!articleSlug.trim() || busy) return;
    setBusy("attach");
    setError(null);
    try {
      const result = await attachChatUnansweredQuery(row.id, {
        article_slug: articleSlug.trim(),
        question_body: questionBody.trim() || null,
      });
      onUpdated(result.unanswered);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  async function onDismiss(): Promise<void> {
    if (busy) return;
    setBusy("dismiss");
    setError(null);
    try {
      const updated = await dismissChatUnansweredQuery(
        row.id,
        dismissReason.trim() || null,
      );
      onUpdated(updated);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  const isAttached = row.status === "ATTACHED";
  const isDismissed = row.status === "DISMISSED";

  return (
    <li className="rounded-md border border-gray-200 bg-white p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
          {row.status} · {new Date(row.created_at).toLocaleString("ru-RU")}
        </span>
        <span className="text-xs text-gray-500">
          author: {row.author_sub}
          {row.chat_session_id ? ` · session: ${row.chat_session_id.slice(0, 8)}…` : ""}
        </span>
      </header>
      <p className="mt-2 whitespace-pre-line text-sm text-gray-900">
        {row.query_masked}
      </p>
      {isAttached && row.attached_article_slug && row.attached_question_id ? (
        <p className="mt-2 text-sm text-gray-700">
          Привязано к статье{" "}
          <Link
            href={`/articles/${row.attached_article_slug}`}
            className="text-brand-strong underline"
          >
            {row.attached_article_slug}
          </Link>
          {" · "}
          <Link
            href={`/admin/article-questions?status=PENDING`}
            className="text-brand-strong underline"
          >
            Q&A id {row.attached_question_id.slice(0, 8)}…
          </Link>
        </p>
      ) : null}
      {isDismissed && row.dismiss_reason ? (
        <p className="mt-2 text-xs italic text-gray-600">
          Причина: {row.dismiss_reason}
        </p>
      ) : null}

      {!isAttached && !isDismissed ? (
        <div className="mt-4 flex flex-col gap-3">
          <fieldset className="flex flex-col gap-2 rounded-md border border-gray-200 p-3">
            <legend className="px-1 text-xs font-medium text-gray-700">
              Привязать к статье
            </legend>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-gray-600">Article slug</span>
              <input
                aria-label="Article slug"
                type="text"
                value={articleSlug}
                onChange={(e) => setArticleSlug(e.target.value)}
                maxLength={200}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
                placeholder="например, rent-contract"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-gray-600">
                Q&A body (опц., переформулировать)
              </span>
              <textarea
                aria-label="Question body override"
                value={questionBody}
                onChange={(e) => setQuestionBody(e.target.value)}
                maxLength={2000}
                rows={2}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
                placeholder={`Default: «${row.query_masked.slice(0, 60)}…»`}
              />
            </label>
            <button
              type="button"
              onClick={onAttach}
              disabled={!articleSlug.trim() || busy !== null}
              className="self-start rounded bg-brand px-3 py-1.5 text-sm font-medium text-ink hover:bg-brand-hover disabled:opacity-50"
            >
              {busy === "attach" ? "…" : "Привязать"}
            </button>
          </fieldset>
          <fieldset className="flex flex-col gap-2 rounded-md border border-gray-200 p-3">
            <legend className="px-1 text-xs font-medium text-gray-700">
              Отклонить
            </legend>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-gray-600">Причина (опц., internal)</span>
              <input
                aria-label="Dismiss reason"
                type="text"
                value={dismissReason}
                onChange={(e) => setDismissReason(e.target.value)}
                maxLength={500}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
              />
            </label>
            <button
              type="button"
              onClick={onDismiss}
              disabled={busy !== null}
              className="self-start rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:opacity-50"
            >
              {busy === "dismiss" ? "…" : "Отклонить"}
            </button>
          </fieldset>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export default function UnansweredModerationPanel({
  initialItems,
  initialTotal,
  statusFilter,
}: Props): JSX.Element {
  const [items, setItems] = useState<ChatUnansweredQuery[]>(initialItems);

  function updateRow(updated: ChatUnansweredQuery): void {
    setItems((prev) =>
      prev.map((r) => (r.id === updated.id ? updated : r)),
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <StatusFilterTabs current={statusFilter} />
      <p className="text-xs text-gray-500">Всего: {initialTotal}</p>
      {items.length === 0 ? (
        <p className="rounded-md border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-600">
          Очередь пуста.
        </p>
      ) : (
        <ol className="flex flex-col gap-3">
          {items.map((r) => (
            <UnansweredRow key={r.id} row={r} onUpdated={updateRow} />
          ))}
        </ol>
      )}
    </section>
  );
}

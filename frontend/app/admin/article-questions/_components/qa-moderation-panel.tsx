"use client";

/**
 * Moderation panel для /admin/article-questions.
 *
 * Per-row actions:
 * - PENDING → answer (textarea) или dismiss (с optional reason).
 * - DISMISSED → answer (всё ещё допустимо: dismiss revert через answer).
 * - ANSWERED → read-only (dismiss блокирован 409 — комментарий объясняет).
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  answerArticleQuestion,
  dismissArticleQuestion,
  type ArticleQuestionAdmin,
  type ArticleQuestionStatus,
} from "@/lib/api/articles";

interface Props {
  initialItems: ArticleQuestionAdmin[];
  initialTotal: number;
  statusFilter: ArticleQuestionStatus;
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
  current: ArticleQuestionStatus;
}): JSX.Element {
  const tabs: { value: ArticleQuestionStatus; label: string }[] = [
    { value: "PENDING", label: "Новые" },
    { value: "ANSWERED", label: "Отвеченные" },
    { value: "DISMISSED", label: "Отклонённые" },
  ];
  return (
    <nav className="flex gap-2 border-b border-gray-200">
      {tabs.map((t) => {
        const active = t.value === current;
        return (
          <Link
            key={t.value}
            href={`/admin/article-questions?status=${t.value}`}
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

function QuestionRow({
  q,
  onUpdated,
}: {
  q: ArticleQuestionAdmin;
  onUpdated: (updated: ArticleQuestionAdmin) => void;
}): JSX.Element {
  const [answerBody, setAnswerBody] = useState("");
  const [dismissReason, setDismissReason] = useState("");
  const [busy, setBusy] = useState<"answer" | "dismiss" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onAnswer(): Promise<void> {
    if (!answerBody.trim() || busy) return;
    setBusy("answer");
    setError(null);
    try {
      const updated = await answerArticleQuestion(q.id, answerBody.trim());
      onUpdated(updated);
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
      const updated = await dismissArticleQuestion(
        q.id,
        dismissReason.trim() || null,
      );
      onUpdated(updated);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  const isAnswered = q.status === "ANSWERED";
  const isDismissed = q.status === "DISMISSED";

  return (
    <li className="rounded-md border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <span
          className={`rounded-md px-2 py-0.5 text-xs font-medium ${
            isAnswered
              ? "bg-green-100 text-green-800"
              : isDismissed
                ? "bg-gray-200 text-gray-700"
                : "bg-yellow-100 text-yellow-900"
          }`}
        >
          {q.status}
        </span>
        <p className="text-xs text-gray-500">
          {new Date(q.created_at).toLocaleString("ru-RU")}
        </p>
      </div>

      <div className="mt-3">
        <p className="text-xs font-medium text-gray-700">Вопрос (article {q.article_id.slice(0, 8)}…):</p>
        <p className="mt-1 text-sm text-gray-800 whitespace-pre-wrap">{q.body}</p>
        <p className="mt-1 text-xs text-gray-500">
          Автор:{" "}
          <code className="font-mono">{q.author_sub.slice(0, 16)}…</code>
        </p>
      </div>

      {isAnswered && q.answer_body ? (
        <div className="mt-3 rounded-md bg-green-50/50 p-3">
          <p className="text-xs font-medium text-green-900">Опубликованный ответ:</p>
          <p className="mt-1 text-sm text-gray-800 whitespace-pre-wrap">{q.answer_body}</p>
          <p className="mt-1 text-xs text-gray-500">
            {q.answered_at
              ? new Date(q.answered_at).toLocaleString("ru-RU")
              : ""}{" "}
            · автор: <code className="font-mono">{(q.answerer_sub ?? "?").slice(0, 16)}…</code>
          </p>
        </div>
      ) : null}

      {isDismissed && q.dismiss_reason ? (
        <p className="mt-3 text-xs text-gray-500">
          Internal note: {q.dismiss_reason}
        </p>
      ) : null}

      {!isAnswered ? (
        <div className="mt-4 flex flex-col gap-2">
          <textarea
            value={answerBody}
            onChange={(e) => setAnswerBody(e.target.value)}
            rows={3}
            maxLength={5000}
            placeholder="Введите ответ (станет публичным сразу после сохранения)"
            className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void onAnswer()}
              disabled={busy !== null || !answerBody.trim()}
              className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-hover disabled:opacity-50"
            >
              {busy === "answer" ? "Сохраняем…" : "Ответить и опубликовать"}
            </button>
            {!isDismissed ? (
              <>
                <input
                  type="text"
                  value={dismissReason}
                  onChange={(e) => setDismissReason(e.target.value)}
                  placeholder="Причина (опционально)"
                  maxLength={500}
                  className="rounded-md border border-gray-300 px-3 py-1.5 text-xs"
                />
                <button
                  type="button"
                  onClick={() => void onDismiss()}
                  disabled={busy !== null}
                  className="rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-800 hover:bg-red-100 disabled:opacity-50"
                >
                  {busy === "dismiss" ? "Отклоняем…" : "Отклонить"}
                </button>
              </>
            ) : null}
          </div>

          {error ? (
            <p
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
            >
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export default function QaModerationPanel({
  initialItems,
  initialTotal,
  statusFilter,
}: Props): JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [items, setItems] = useState<ArticleQuestionAdmin[]>(initialItems);

  function onUpdated(updated: ArticleQuestionAdmin): void {
    // Если row меняет статус → больше не matches'ит current filter → убираем.
    if (updated.status !== statusFilter) {
      setItems((prev) => prev.filter((p) => p.id !== updated.id));
    } else {
      setItems((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p)),
      );
    }
    // Refresh page — total recount via server.
    router.refresh();
    void searchParams; // unused but referenced for forward-compat
  }

  return (
    <section className="flex flex-col gap-4">
      <StatusFilterTabs current={statusFilter} />
      <p className="text-xs text-gray-600">
        Показано: {items.length} (всего {initialTotal} в этом фильтре).
      </p>
      {items.length === 0 ? (
        <p className="text-sm text-gray-600">Нет элементов в этом фильтре.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((q) => (
            <QuestionRow key={q.id} q={q} onUpdated={onUpdated} />
          ))}
        </ul>
      )}
    </section>
  );
}

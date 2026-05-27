"use client";

/**
 * Q&A section под статьёй (ТЗ §2, 2026-05-28).
 *
 * Renders:
 * - Список ANSWERED questions с answer'ами (если есть).
 * - Submit form для logged users (cookie session).
 *
 * Submission flow:
 * 1. User вводит вопрос → submit.
 * 2. Backend creates PENDING; user видит «Вопрос отправлен на модерацию».
 * 3. После staff answer'а — appears в публичном списке.
 *
 * ФЗ-152: disclaimer что вопрос станет публичным после модерации.
 * `author_sub` НЕ показывается в public list (анонимизация).
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  listArticleQuestions,
  submitArticleQuestion,
  type ArticleQuestionPublic,
} from "@/lib/api/articles";

interface Props {
  slug: string;
  /** true если cookie session есть (server-side determined в page.tsx). */
  isLoggedIn: boolean;
}

const MAX_BODY = 2000;

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

export default function ArticleQaSection({ slug, isLoggedIn }: Props): JSX.Element {
  const [questions, setQuestions] = useState<ArticleQuestionPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState(false);

  async function load(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const resp = await listArticleQuestions(slug);
      setQuestions(resp.data);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    if (!body.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitArticleQuestion(slug, body.trim());
      setBody("");
      setSubmitSuccess(true);
      // Не делаем reload — submission appears в moderation queue, не в public list.
      // Опционально: показать «Ваш вопрос отправлен» и спрятать форму на пару секунд.
      setTimeout(() => setSubmitSuccess(false), 5000);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mt-6 rounded-md border border-gray-200 bg-gray-50/30 p-6">
      <h2 className="text-lg font-semibold">Вопросы и ответы</h2>
      <p className="mt-1 text-xs text-gray-600">
        Ниже — вопросы пользователей и официальные ответы команды reHome.
      </p>

      {loading ? (
        <p className="mt-4 text-sm text-gray-600">Загружаем вопросы…</p>
      ) : questions.length === 0 ? (
        <p className="mt-4 text-sm text-gray-600">
          Пока нет ответов на вопросы. Задайте свой первым!
        </p>
      ) : (
        <ul className="mt-4 flex flex-col gap-4">
          {questions.map((q) => (
            <li
              key={q.id}
              className="rounded-md border border-gray-200 bg-white p-4"
            >
              <p className="text-sm font-medium text-gray-900">Вопрос:</p>
              <p className="mt-1 text-sm text-gray-700">{q.body}</p>
              <p className="mt-3 text-sm font-medium text-blue-900">Ответ:</p>
              <p className="mt-1 text-sm whitespace-pre-wrap text-gray-700">
                {q.answer_body}
              </p>
              <p className="mt-2 text-xs text-gray-500">
                {new Date(q.answered_at).toLocaleDateString("ru-RU")}
              </p>
            </li>
          ))}
        </ul>
      )}

      {/* Submit form */}
      <div className="mt-6 border-t border-gray-200 pt-4">
        {isLoggedIn ? (
          <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-2">
            <label className="text-sm font-medium" htmlFor="qa-body">
              Задать свой вопрос
            </label>
            <textarea
              id="qa-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              maxLength={MAX_BODY}
              rows={3}
              disabled={submitting}
              placeholder="Например: Когда заработает оплата картой?"
              className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:opacity-50"
            />
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-500">
                После проверки модератором ваш вопрос и ответ станут видны
                публично. Не указывайте персональные данные (телефон, email).
              </p>
              <span className="text-xs text-gray-400">
                {body.length}/{MAX_BODY}
              </span>
            </div>

            {submitSuccess ? (
              <p className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-800">
                Вопрос отправлен на модерацию. После ответа он появится здесь.
              </p>
            ) : null}

            {error ? (
              <p
                role="alert"
                className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
              >
                {error}
              </p>
            ) : null}

            <button
              type="submit"
              disabled={submitting || !body.trim()}
              className="self-start rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
            >
              {submitting ? "Отправляем…" : "Задать вопрос"}
            </button>
          </form>
        ) : (
          <p className="text-sm text-gray-600">
            <a href="/login" className="text-blue-600 hover:underline">
              Войдите
            </a>
            , чтобы задать вопрос.
          </p>
        )}
      </div>
    </section>
  );
}

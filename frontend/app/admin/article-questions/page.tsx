/**
 * /admin/article-questions — moderation queue Q&A (ТЗ §2, 2026-05-28).
 *
 * Server Component fetch initial filter=PENDING. Клиент-side panel
 * для answer/dismiss actions.
 */

import Nav from "@/app/_components/nav";
import {
  listAdminArticleQuestions,
  type ArticleQuestionStatus,
} from "@/lib/api/articles";
import { ApiError } from "@/lib/api/client";

import QaModerationPanel from "./_components/qa-moderation-panel";

interface PageProps {
  searchParams: Promise<{ status?: string }>;
}

const VALID_STATUSES: readonly ArticleQuestionStatus[] = [
  "PENDING",
  "ANSWERED",
  "DISMISSED",
];

function parseStatus(raw: string | undefined): ArticleQuestionStatus | undefined {
  if (!raw) return undefined;
  return (VALID_STATUSES as readonly string[]).includes(raw)
    ? (raw as ArticleQuestionStatus)
    : undefined;
}

export default async function AdminQuestionsPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const statusFilter = parseStatus(params.status) ?? "PENDING";

  let initial;
  let error: string | null = null;
  try {
    initial = await listAdminArticleQuestions({
      status: statusFilter,
      limit: 100,
    });
  } catch (err) {
    if (err instanceof ApiError) {
      error =
        err.status === 401
          ? "Требуется авторизация."
          : err.status === 403
            ? "Требуется staff_admin scope."
            : `Ошибка ${err.status}`;
      initial = { data: [], total: 0 };
    } else {
      throw err;
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            Вопросы к статьям
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Модерация Q&A — ответ публикует вопрос+ответ на странице статьи.
            ANSWERED уже опубликовано публично; dismiss недоступен.
          </p>
        </header>
        {error ? (
          <p
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </p>
        ) : null}
        <QaModerationPanel
          initialItems={initial.data}
          initialTotal={initial.total}
          statusFilter={statusFilter}
        />
      </main>
    </>
  );
}

/**
 * /admin/chat-unanswered-queries — capture queue (2026-05-29).
 *
 * Server Component fetch initial filter=NEW. Per-row attach/dismiss
 * actions через client panel.
 */

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import {
  listChatUnansweredQueries,
  type ChatUnansweredStatus,
} from "@/lib/api/chat-unanswered";

import UnansweredModerationPanel from "./_components/unanswered-moderation-panel";

interface PageProps {
  searchParams: Promise<{ status?: string }>;
}

const VALID_STATUSES: readonly ChatUnansweredStatus[] = [
  "NEW",
  "ATTACHED",
  "DISMISSED",
];

function parseStatus(
  raw: string | undefined,
): ChatUnansweredStatus | undefined {
  if (!raw) return undefined;
  return (VALID_STATUSES as readonly string[]).includes(raw)
    ? (raw as ChatUnansweredStatus)
    : undefined;
}

export default async function AdminChatUnansweredPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const statusFilter = parseStatus(params.status) ?? "NEW";

  let initial;
  let error: string | null = null;
  try {
    initial = await listChatUnansweredQueries({
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
            Запросы без ответа из чата
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            RAG не нашёл подходящих статей — staff решает либо привязать
            запрос к статье (создаст PENDING Q&A для последующего ответа),
            либо отметить как out-of-scope.
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
        <UnansweredModerationPanel
          initialItems={initial.data}
          initialTotal={initial.total}
          statusFilter={statusFilter}
        />
      </main>
    </>
  );
}

/**
 * /admin/collaborators/onboarding — очередь онбординга (ADR-0014/0015, ТЗ §10.8).
 *
 * Pre-filtered list для `status=PENDING_REVIEW`. Эти записи — заявки
 * через публичную форму (onboarding_source='form') либо staff-invited
 * черновики, ожидающие активации. STAFF+ кликает Активировать /
 * Приостановить inline без drill-down.
 *
 * Сортировка по created_at не реализуется фронтом — backend list
 * endpoint возвращает в дефолтном порядке (newest first per ADR-0014).
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { listCollaborators } from "@/lib/api/collaborators";
import type {
  CollaboratorInternal,
  CollaboratorPublic,
} from "@/lib/api/types";

import OnboardingQueueTable from "../_components/onboarding-queue-table";

interface PageProps {
  searchParams: Promise<{ cursor?: string }>;
}

const PAGE_SIZE = 25;

export default async function CollaboratorsOnboardingPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;

  let data: Array<CollaboratorPublic | CollaboratorInternal> = [];
  let pagination: { cursor_next: string | null; has_more: boolean } = {
    cursor_next: null,
    has_more: false,
  };
  let error: string | null = null;
  try {
    const resp = await listCollaborators({
      status: "PENDING_REVIEW",
      cursor: params.cursor,
      limit: PAGE_SIZE,
    });
    data = resp.data;
    pagination = resp.pagination;
  } catch (err) {
    if (err instanceof ApiError) {
      error = `${err.status}: ${err.message}`;
    } else {
      error = err instanceof Error ? err.message : "Ошибка загрузки";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-8">
        <Link
          href="/admin/collaborators"
          className="text-sm text-gray-600 hover:underline"
        >
          ← К списку коллаборантов
        </Link>
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">
            Очередь онбординга
          </h1>
          <span className="rounded-full bg-yellow-100 px-3 py-1 text-xs font-medium text-yellow-800">
            {data.length} заявок
          </span>
        </header>

        <p className="text-xs text-gray-600">
          Коллаборанты в статусе <code>PENDING_REVIEW</code> — заявки через
          публичную форму либо staff-invited черновики, ожидающие активации
          (ТЗ §10.8.1). Активируйте после проверки контакта, либо
          приостановите с указанием причины.
        </p>

        {error ? (
          <p
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </p>
        ) : (
          <OnboardingQueueTable data={data} />
        )}

        {pagination.cursor_next ? (
          <Link
            href={`/admin/collaborators/onboarding?cursor=${encodeURIComponent(
              pagination.cursor_next,
            )}`}
            className="self-start rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            Следующая страница →
          </Link>
        ) : null}
      </main>
    </>
  );
}

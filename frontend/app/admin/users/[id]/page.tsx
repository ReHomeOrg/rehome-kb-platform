/**
 * /admin/users/[id] — KB user detail + edit form (#257).
 */

import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { getKbUser } from "@/lib/api/admin-users";
import { ApiError } from "@/lib/api/client";
import type { KbUser } from "@/lib/api/types";

import KbUserEditForm from "../_components/kb-user-edit-form";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function KbUserDetailPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { id } = await params;

  let user: KbUser | undefined;
  let error: string | undefined;
  try {
    user = await getKbUser(id);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 404) {
        notFound();
      }
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить пользователя.";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-6">
        <a
          href="/admin/users"
          className="mb-3 inline-block text-xs text-blue-700 underline hover:text-blue-900"
        >
          ← Назад к списку
        </a>
        <h1 className="mb-4 text-2xl font-semibold">KB user</h1>

        {error !== undefined ? (
          <div
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
          >
            {error}
          </div>
        ) : null}

        {user ? <KbUserEditForm initial={user} /> : null}
      </main>
    </>
  );
}

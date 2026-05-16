/**
 * /admin/collaborators/[id] — detail + edit form (ADR-0014, ТЗ §10).
 *
 * Server Component fetch'ит detail per scope (Public/Internal/Admin).
 * Edit form available только для staff_admin (visual gate; backend
 * проверяет реально).
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getCollaborator } from "@/lib/api/collaborators";
import type {
  CollaboratorAdmin,
  CollaboratorInternal,
} from "@/lib/api/types";

import CollaboratorForm from "../_components/collaborator-form";

interface PageProps {
  params: Promise<{ id: string }>;
}

function isInternal(
  c: unknown,
): c is CollaboratorInternal | CollaboratorAdmin {
  return typeof c === "object" && c !== null && "name" in c;
}

export default async function CollaboratorDetailPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { id } = await params;
  let collaborator;
  try {
    collaborator = await getCollaborator(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  // Если backend вернул Public schema — у staff'а нет прав на edit
  // (но для admin pages мы expect'аем STAFF+). Defensive — показываем
  // только read-only поля.
  const internal = isInternal(collaborator) ? collaborator : null;

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <Link
          href="/admin/collaborators"
          className="text-sm text-gray-600 hover:underline"
        >
          ← К списку
        </Link>
        <header className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {internal?.name ?? collaborator.brand_name ?? "Коллаборант"}
            </h1>
            <p className="mt-1 text-xs text-gray-500">
              {collaborator.type} · {collaborator.financial_group} · {collaborator.status}
            </p>
          </div>
        </header>

        {internal ? (
          <CollaboratorForm initial={internal} />
        ) : (
          <section className="rounded-md border border-gray-200 p-4">
            <p className="text-sm text-gray-700">
              У вас нет прав на редактирование этого коллаборанта. Доступно
              только публичное представление.
            </p>
            <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="font-medium text-gray-700">Бренд</dt>
                <dd>{collaborator.brand_name ?? "—"}</dd>
              </div>
              <div>
                <dt className="font-medium text-gray-700">География</dt>
                <dd>{collaborator.service_area}</dd>
              </div>
              <div>
                <dt className="font-medium text-gray-700">Часы работы</dt>
                <dd>{collaborator.working_hours ?? "—"}</dd>
              </div>
              <div>
                <dt className="font-medium text-gray-700">Сайт</dt>
                <dd>{collaborator.website ?? "—"}</dd>
              </div>
            </dl>
          </section>
        )}
      </main>
    </>
  );
}

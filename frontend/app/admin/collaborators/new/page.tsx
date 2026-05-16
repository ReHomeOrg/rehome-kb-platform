/**
 * /admin/collaborators/new — create form (ADR-0014, ТЗ §10).
 *
 * Server Component shell — реальный form в client component
 * (`CollaboratorForm`).
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";

import CollaboratorForm from "../_components/collaborator-form";

export default function NewCollaboratorPage(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-8">
        <Link
          href="/admin/collaborators"
          className="text-sm text-gray-600 hover:underline"
        >
          ← К списку
        </Link>
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            Новый коллаборант
          </h1>
          <p className="mt-2 text-xs text-gray-600">
            Требует роли staff_admin. Backend auditит создание. D-группа
            (УК/аварийки) auto-ACTIVE, остальные — DRAFT.
          </p>
        </header>
        <CollaboratorForm />
      </main>
    </>
  );
}

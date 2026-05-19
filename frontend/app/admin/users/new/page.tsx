/**
 * /admin/users/new — KB user create form (#260).
 */

import Nav from "@/app/_components/nav";

import KbUserCreateForm from "../_components/kb-user-create-form";

export default function NewKbUserPage(): JSX.Element {
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
        <h1 className="mb-4 text-2xl font-semibold">Новый KB user</h1>
        <KbUserCreateForm />
      </main>
    </>
  );
}

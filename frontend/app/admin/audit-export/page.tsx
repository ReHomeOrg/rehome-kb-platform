/**
 * /admin/audit-export — POST audit-log export form (#261).
 *
 * staff_admin / staff_legal scope. Backend — #239.
 */

import Nav from "@/app/_components/nav";

import AuditExportForm from "./_components/audit-export-form";

export default function AuditExportPage(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-6">
        <a
          href="/admin"
          className="mb-3 inline-block text-xs text-brand-strong underline hover:text-ink"
        >
          ← Dashboard
        </a>
        <h1 className="mb-2 text-2xl font-semibold">Экспорт аудит-лога</h1>
        <p className="mb-4 text-sm text-gray-600">
          Для регуляторов / суда. Sync execution в request, result_url
          возвращается сразу — указывает на existing CSV endpoint с
          теми же filters. Reason — обязательно для compliance trail.
        </p>
        <AuditExportForm />
      </main>
    </>
  );
}

/**
 * /admin/maintenance — operational triad UI (#259).
 *
 * staff_admin scope. Buttons:
 * - POST /admin/reindex — full rebuild article embeddings.
 * - DELETE /admin/cache — honest stub (no cache layer; audit only).
 *
 * Both — client-side components с confirm + result display.
 */

import Nav from "@/app/_components/nav";

import CacheInvalidateButton from "./_components/cache-invalidate-button";
import ReindexButton from "./_components/reindex-button";

export default function MaintenancePage(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-6">
        <a
          href="/admin"
          className="mb-3 inline-block text-xs text-blue-700 underline hover:text-blue-900"
        >
          ← Dashboard
        </a>
        <h1 className="mb-2 text-2xl font-semibold">Maintenance</h1>
        <p className="mb-6 text-sm text-gray-600">
          Операционные действия. Каждое создаёт audit-log запись;
          reindex — admin_task с tracking через GET /admin/tasks/{"{"}id{"}"} (UI
          tracking — backlog).
        </p>

        <section className="mb-6 rounded-md border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-medium text-gray-700">
            Принудительная переиндексация
          </h2>
          <p className="mb-3 text-xs text-gray-600">
            Полный пересчёт embeddings для PUBLISHED articles. Sync execution
            в request (~N × embed_latency). Production-scale — backlog
            (async worker через ADR&apos;у).
          </p>
          <ReindexButton />
        </section>

        <section className="mb-6 rounded-md border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-medium text-gray-700">
            Инвалидация кеша
          </h2>
          <p className="mb-3 text-xs text-gray-600">
            Honest stub: backend не имеет explicit cache layer. Endpoint
            записывает audit запись (compliance trail для будущего worker&apos;а).
          </p>
          <CacheInvalidateButton />
        </section>
      </main>
    </>
  );
}

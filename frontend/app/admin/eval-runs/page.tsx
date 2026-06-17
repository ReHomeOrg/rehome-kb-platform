/**
 * /admin/eval-runs — eval-стенд история прогонов (#248, backend #244).
 *
 * staff_admin / staff_legal scope (backend gate). Non-admin → 403 →
 * graceful UX message. SSR fetches с cookie attach.
 *
 * POST endpoint (запустить новый run) — backlog: нужен CSRF + form UX
 * со выбором providers / test_set.
 */

import Nav from "@/app/_components/nav";
import { listEvalRuns } from "@/lib/api/admin-eval-runs";
import { ApiError } from "@/lib/api/client";
import type { EvalRunSummary } from "@/lib/api/types";

import EvalRunsTable from "./_components/eval-runs-table";
import StartRunForm from "./_components/start-run-form";

interface PageProps {
  searchParams: Promise<{
    provider?: string;
  }>;
}

const PAGE_LIMIT = 50;

export default async function EvalRunsPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const provider = params.provider?.trim() || undefined;

  let runs: EvalRunSummary[] = [];
  let error: string | undefined;
  try {
    const body = await listEvalRuns({ provider, limit: PAGE_LIMIT });
    runs = body.data;
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin / staff_legal.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить eval-runs.";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <h1 className="mb-4 text-2xl font-semibold">Eval-стенд: история прогонов</h1>
        <p className="mb-4 text-sm text-gray-600">
          OpenAPI 04 §listEvalRuns. MVP: mock provider + smoke test_set
          (10 pairs из golden.jsonl). Real LLM providers — backlog
          (требуют env credentials per ADR-0013).
        </p>
        <form
          method="get"
          action="/admin/eval-runs"
          role="search"
          aria-label="Eval runs filters"
          className="mb-4 flex flex-wrap items-end gap-3 rounded-md border border-gray-200 bg-gray-50 p-3"
        >
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-600">Provider</span>
            <input
              type="text"
              name="provider"
              defaultValue={params.provider ?? ""}
              placeholder="напр. mock"
              maxLength={64}
              aria-label="Filter runs by provider"
              className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
            />
          </label>
          <button
            type="submit"
            className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-hover"
          >
            Применить
          </button>
          {provider ? (
            <a
              href="/admin/eval-runs"
              aria-label="Reset filter"
              className="text-xs text-blue-700 underline hover:text-blue-900"
            >
              Сбросить
            </a>
          ) : null}
        </form>
        <StartRunForm />
        <EvalRunsTable runs={runs} error={error} />
      </main>
    </>
  );
}

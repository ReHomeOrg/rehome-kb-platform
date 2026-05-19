/**
 * /admin/llm-providers — read-only LLM providers list (#252, backend #228).
 *
 * staff_admin scope. PUT /admin/llm/active — backlog (ADR-0019).
 */

import Nav from "@/app/_components/nav";
import { listLlmProviders } from "@/lib/api/admin-llm-providers";
import { ApiError } from "@/lib/api/client";
import type { LlmProvider, LlmProviderStatus } from "@/lib/api/types";

import SwitchProviderButton from "./_components/switch-provider-button";

function statusBadge(status: LlmProviderStatus): JSX.Element {
  const colors: Record<LlmProviderStatus, string> = {
    ACTIVE: "bg-green-100 text-green-800",
    INACTIVE: "bg-gray-100 text-gray-700",
    EXPERIMENTAL: "bg-amber-100 text-amber-900",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status]}`}>
      {status}
    </span>
  );
}

function formatCost(v: number | null): string {
  if (v === null) return "—";
  return `₽${v.toFixed(2)}`;
}

export default async function LlmProvidersPage(): Promise<JSX.Element> {
  let providers: LlmProvider[] = [];
  let error: string | undefined;
  try {
    const body = await listLlmProviders();
    providers = body.data;
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить providers.";
    }
  }

  const current = providers.find((p) => p.is_current);

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <h1 className="mb-2 text-2xl font-semibold">LLM providers</h1>
        <p className="mb-4 text-sm text-gray-600">
          OpenAPI 04 §listLlmProviders. Current provider derives из
          env-config (LLM_PROVIDER). Switch — backlog (ADR-0019, PUT
          /admin/llm/active с MFA).
        </p>

        {current ? (
          <div className="mb-4 rounded-md border border-green-200 bg-green-50 p-3 text-sm">
            Текущий активный: <code className="font-mono">{current.id}</code>{" "}
            ({current.name})
          </div>
        ) : null}

        {error !== undefined ? (
          <div
            role="alert"
            className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
          >
            {error}
          </div>
        ) : null}

        {providers.length > 0 ? (
          <div className="overflow-x-auto rounded-md border border-gray-200">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="px-3 py-2">ID</th>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Vendor</th>
                  <th className="px-3 py-2">Model</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Current</th>
                  <th className="px-3 py-2">In ₽/1M tok</th>
                  <th className="px-3 py-2">Out ₽/1M tok</th>
                  <th className="px-3 py-2">Context</th>
                  <th className="px-3 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((p) => (
                  <tr key={p.id} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-mono">{p.id}</td>
                    <td className="px-3 py-2">{p.name}</td>
                    <td className="px-3 py-2 text-gray-700">{p.vendor ?? "—"}</td>
                    <td className="px-3 py-2 font-mono text-gray-700">
                      {p.model ?? "—"}
                    </td>
                    <td className="px-3 py-2">{statusBadge(p.status)}</td>
                    <td className="px-3 py-2">
                      {p.is_current ? (
                        <span
                          className="text-green-700"
                          aria-label="Active provider"
                        >
                          ✓
                        </span>
                      ) : (
                        ""
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-700">
                      {formatCost(p.cost_per_1m_input_tokens_rub)}
                    </td>
                    <td className="px-3 py-2 text-gray-700">
                      {formatCost(p.cost_per_1m_output_tokens_rub)}
                    </td>
                    <td className="px-3 py-2 text-gray-700">
                      {p.max_context_tokens?.toLocaleString() ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      {p.is_current ? null : (
                        <SwitchProviderButton providerId={p.id} />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </main>
    </>
  );
}

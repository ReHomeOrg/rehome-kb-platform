"use client";

/**
 * Start eval run form (#258). POST /admin/llm/eval-runs (backend #244).
 *
 * MVP: providers=["mock"] + test_set="smoke" only. Other combos backend
 * reject'нет 422 — UI shows backend error.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { startEvalRun } from "@/lib/api/admin-eval-runs";
import type { EvalTestSet } from "@/lib/api/types";

const AVAILABLE_PROVIDERS = ["mock", "gigachat", "yandex_gpt", "vllm"] as const;
const TEST_SETS: EvalTestSet[] = ["smoke", "full", "custom"];

export default function StartRunForm(): JSX.Element {
  const router = useRouter();
  const [providers, setProviders] = useState<Set<string>>(new Set(["mock"]));
  const [testSet, setTestSet] = useState<EvalTestSet>("smoke");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();

  function toggleProvider(p: string): void {
    const next = new Set(providers);
    if (next.has(p)) next.delete(p);
    else next.add(p);
    setProviders(next);
  }

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    setSuccess(undefined);
    if (providers.size === 0) {
      setError("Выберите хотя бы один provider.");
      setBusy(false);
      return;
    }
    try {
      const resp = await startEvalRun({
        providers: Array.from(providers),
        test_set: testSet,
      });
      setSuccess(resp.run_id);
      // Refresh server-side list page.
      router.refresh();
      // Reset form (kept providers/testSet selections для convenience).
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Ошибка ${e.status}: ${e.message}`);
      } else {
        setError("Не удалось запустить run.");
      }
    }
    setBusy(false);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mb-6 rounded-md border border-gray-200 bg-white p-4"
      aria-label="Start new eval run"
    >
      <h2 className="mb-3 text-sm font-medium text-gray-700">
        Запустить новый прогон
      </h2>
      <p className="mb-3 text-xs text-gray-600">
        MVP: поддерживаются только <code>providers=[&quot;mock&quot;]</code> +{" "}
        <code>test_set=&quot;smoke&quot;</code>. Other combos → 422 от backend
        per ADR-0013.
      </p>

      <fieldset className="mb-3">
        <legend className="text-xs text-gray-600">Providers</legend>
        <div className="mt-1 flex flex-wrap gap-3 text-xs">
          {AVAILABLE_PROVIDERS.map((p) => (
            <label key={p} className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={providers.has(p)}
                onChange={() => toggleProvider(p)}
                aria-label={`Provider ${p}`}
              />
              <span className="font-mono">{p}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="mb-3">
        <legend className="text-xs text-gray-600">Test set</legend>
        <div className="mt-1 flex flex-wrap gap-3 text-xs">
          {TEST_SETS.map((t) => (
            <label key={t} className="inline-flex items-center gap-1">
              <input
                type="radio"
                name="test_set"
                value={t}
                checked={testSet === t}
                onChange={() => setTestSet(t)}
                aria-label={`Test set ${t}`}
              />
              <span>{t}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {error ? (
        <div
          role="alert"
          className="mb-3 rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-900"
        >
          {error}
        </div>
      ) : null}
      {success ? (
        <div
          role="status"
          className="mb-3 rounded-md border border-green-200 bg-green-50 p-2 text-xs text-green-900"
        >
          Run запущен:{" "}
          <a
            href={`/admin/tasks/${success}`}
            className="font-mono text-brand-strong underline hover:text-ink"
          >
            {success.slice(0, 8)}
          </a>{" "}
          → status
        </div>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-ink hover:bg-brand-hover disabled:opacity-50"
      >
        {busy ? "Запуск…" : "Запустить"}
      </button>
    </form>
  );
}

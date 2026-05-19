"use client";

/**
 * Reindex trigger button (#259). POST /admin/reindex scope=articles (real
 * execution per #240).
 */

import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  triggerReindex,
  type ReindexScope,
} from "@/lib/api/admin-maintenance";

const SCOPES: ReindexScope[] = ["articles", "all", "documents", "premises_cards"];

export default function ReindexButton(): JSX.Element {
  const [scope, setScope] = useState<ReindexScope>("articles");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [taskId, setTaskId] = useState<string | undefined>();

  async function handleClick(): Promise<void> {
    const msg =
      scope === "articles" || scope === "all"
        ? `Запустить reindex для scope=${scope}? Sync execution, ~N×embed_latency.`
        : `scope=${scope} — honest stub (нет indexer'а). Создаст admin_task без actual work. Продолжить?`;
    if (!window.confirm(msg)) return;
    setBusy(true);
    setError(undefined);
    setTaskId(undefined);
    try {
      const resp = await triggerReindex(scope);
      setTaskId(resp.task_id);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Ошибка ${e.status}: ${e.message}`);
      } else {
        setError("Не удалось запустить.");
      }
    }
    setBusy(false);
  }

  return (
    <div className="space-y-3">
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Scope</span>
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value as ReindexScope)}
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Reindex scope"
        >
          {SCOPES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
      >
        {busy ? "Запуск…" : "Запустить reindex"}
      </button>

      {error ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-900"
        >
          {error}
        </div>
      ) : null}

      {taskId ? (
        <div
          role="status"
          className="rounded-md border border-green-200 bg-green-50 p-2 text-xs text-green-900"
        >
          Task создан:{" "}
          <code className="font-mono">{taskId}</code> (статус: COMPLETED;
          MVP без real async)
        </div>
      ) : null}
    </div>
  );
}

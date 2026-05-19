"use client";

/**
 * Cache invalidate button (#259). DELETE /admin/cache (honest stub
 * per #238).
 */

import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  invalidateCache,
  type CacheScope,
} from "@/lib/api/admin-maintenance";

const SCOPES: CacheScope[] = ["all", "articles", "documents", "premises_cards", "search"];

export default function CacheInvalidateButton(): JSX.Element {
  const [scope, setScope] = useState<CacheScope>("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();

  async function handleClick(): Promise<void> {
    if (
      !window.confirm(
        `Инвалидировать кеш scope=${scope}? Honest stub: записывает audit-log; без реального cache layer — no-op.`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(undefined);
    setSuccess(undefined);
    try {
      const resp = await invalidateCache(scope);
      setSuccess(`${resp.status}: ${resp.scope}`);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Ошибка ${e.status}: ${e.message}`);
      } else {
        setError("Не удалось.");
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
          onChange={(e) => setScope(e.target.value as CacheScope)}
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Cache scope"
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
        {busy ? "Инвалидация…" : "Инвалидировать кеш"}
      </button>

      {error ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-900"
        >
          {error}
        </div>
      ) : null}

      {success ? (
        <div
          role="status"
          className="rounded-md border border-green-200 bg-green-50 p-2 text-xs text-green-900"
        >
          {success}
        </div>
      ) : null}
    </div>
  );
}

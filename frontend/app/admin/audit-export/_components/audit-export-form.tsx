"use client";

/**
 * Audit-log export form (#261). POST /admin/audit-log/export.
 */

import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  startAuditExport,
  type AuditExportFormat,
} from "@/lib/api/admin-audit-export";

const FORMATS: AuditExportFormat[] = ["csv", "json"];

function defaultFrom(): string {
  const d = new Date();
  d.setDate(d.getDate() - 30);
  return toLocal(d);
}

function defaultTo(): string {
  return toLocal(new Date());
}

function toLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function toIso(local: string): string {
  return new Date(local).toISOString();
}

export default function AuditExportForm(): JSX.Element {
  const [fromInput, setFromInput] = useState(defaultFrom());
  const [toInput, setToInput] = useState(defaultTo());
  const [actorSub, setActorSub] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [action, setAction] = useState("");
  const [format, setFormat] = useState<AuditExportFormat>("csv");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [result, setResult] = useState<{ taskId: string } | undefined>();

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    setResult(undefined);
    if (!reason.trim()) {
      setError("Reason обязателен (compliance trail).");
      setBusy(false);
      return;
    }
    const filters: Record<string, string> = {};
    if (actorSub.trim()) filters.actor_sub = actorSub.trim();
    if (resourceType.trim()) filters.resource_type = resourceType.trim();
    if (action.trim()) filters.action = action.trim();
    try {
      const resp = await startAuditExport({
        from: toIso(fromInput),
        to: toIso(toInput),
        filters: Object.keys(filters).length > 0 ? filters : undefined,
        format,
        reason: reason.trim(),
      });
      setResult({ taskId: resp.task_id });
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Ошибка ${e.status}: ${e.message}`);
      } else {
        setError("Не удалось запустить export.");
      }
    }
    setBusy(false);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4"
      aria-label="Audit-log export"
    >
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-gray-600">С (от)</span>
          <input
            type="datetime-local"
            value={fromInput}
            onChange={(e) => setFromInput(e.target.value)}
            required
            className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            aria-label="From datetime"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-gray-600">По (до)</span>
          <input
            type="datetime-local"
            value={toInput}
            onChange={(e) => setToInput(e.target.value)}
            required
            className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            aria-label="To datetime"
          />
        </label>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-xs text-gray-600">Filters (optional)</legend>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-gray-500">actor_sub</span>
          <input
            type="text"
            value={actorSub}
            onChange={(e) => setActorSub(e.target.value)}
            maxLength={200}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            aria-label="Filter by actor_sub"
            placeholder="UUID / email"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-gray-500">resource_type</span>
          <input
            type="text"
            value={resourceType}
            onChange={(e) => setResourceType(e.target.value)}
            maxLength={64}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            aria-label="Filter by resource_type"
            placeholder="article / vault_secret / ..."
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-gray-500">action</span>
          <input
            type="text"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            maxLength={64}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            aria-label="Filter by action"
            placeholder="articles.created / vault.unlock.failed / ..."
          />
        </label>
      </fieldset>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Format</span>
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as AuditExportFormat)}
          className="w-32 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Format"
        >
          {FORMATS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Reason (compliance)*</span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          maxLength={500}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Reason"
          placeholder="Запрос РКН №123 от 2026-05-01"
        />
      </label>

      {error ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900"
        >
          {error}
        </div>
      ) : null}

      {result ? (
        <div
          role="status"
          className="space-y-2 rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-900"
        >
          <div>
            Task:{" "}
            <a
              href={`/admin/tasks/${result.taskId}`}
              className="font-mono text-blue-700 underline hover:text-blue-900"
            >
              {result.taskId}
            </a>{" "}
            → status + download
          </div>
        </div>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
      >
        {busy ? "Запуск…" : "Запустить export"}
      </button>
    </form>
  );
}

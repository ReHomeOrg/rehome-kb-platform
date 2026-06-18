"use client";

/**
 * Security incident edit form (#255). Client-side mutations:
 * - status transitions (OPEN → INVESTIGATING → RESOLVED / FALSE_POSITIVE).
 * - resolution_note (free text).
 * - rkn_notified_at (datetime, для compliance: 24h факт / 72h состав).
 *
 * Backend (#231) enforces lifecycle invariants (409 на reverse
 * terminal). 404 surface'ится в parent page.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  patchSecurityIncident,
  type SecurityIncidentPatchInput,
} from "@/lib/api/admin-security-incidents";
import type { IncidentStatus, SecurityIncident } from "@/lib/api/types";

interface Props {
  initial: SecurityIncident;
}

const STATUSES: IncidentStatus[] = [
  "OPEN",
  "INVESTIGATING",
  "RESOLVED",
  "FALSE_POSITIVE",
];

function toLocalDatetime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalDatetime(local: string): string | null {
  if (!local) return null;
  return new Date(local).toISOString();
}

export default function IncidentEditForm({ initial }: Props): JSX.Element {
  const router = useRouter();
  const [status, setStatus] = useState<IncidentStatus>(initial.status);
  const [resolutionNote, setResolutionNote] = useState(
    initial.resolution_note ?? "",
  );
  const [rknNotifiedAt, setRknNotifiedAt] = useState(
    toLocalDatetime(initial.rkn_notified_at),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();

  const isTerminal = status === "RESOLVED" || status === "FALSE_POSITIVE";
  const wasTerminal =
    initial.status === "RESOLVED" || initial.status === "FALSE_POSITIVE";

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    const patch: SecurityIncidentPatchInput = {};
    if (status !== initial.status) patch.status = status;
    if (resolutionNote !== (initial.resolution_note ?? "")) {
      patch.resolution_note = resolutionNote || null;
    }
    const newRknIso = fromLocalDatetime(rknNotifiedAt);
    if (newRknIso !== initial.rkn_notified_at) {
      patch.rkn_notified_at = newRknIso;
    }
    if (Object.keys(patch).length === 0) {
      setBusy(false);
      return;
    }
    try {
      await patchSecurityIncident(initial.id, patch);
      router.push("/admin/security-incidents");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Ошибка ${e.status}: ${e.message}`);
      } else {
        setError("Не удалось сохранить изменения.");
      }
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="rounded-md border border-gray-200 bg-white p-4">
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <dt className="text-gray-600">ID</dt>
          <dd className="font-mono text-gray-900">{initial.id}</dd>
          <dt className="text-gray-600">Тип</dt>
          <dd className="font-mono">{initial.incident_type}</dd>
          <dt className="text-gray-600">Severity</dt>
          <dd className="font-mono">{initial.severity}</dd>
          <dt className="text-gray-600">Обнаружен</dt>
          <dd className="text-gray-900">
            {new Date(initial.detected_at).toLocaleString("ru-RU")} (
            {initial.detected_by})
          </dd>
          <dt className="text-gray-600">РКН требуется</dt>
          <dd>{initial.rkn_notification_required ? "да" : "нет"}</dd>
        </dl>
      </div>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Status</span>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as IncidentStatus)}
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Status"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {wasTerminal && !isTerminal ? (
          <span className="text-xs text-amber-700">
            ⚠ Backend вернёт 409: reverse из terminal status&apos;а запрещён.
          </span>
        ) : null}
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Resolution note</span>
        <textarea
          value={resolutionNote}
          onChange={(e) => setResolutionNote(e.target.value)}
          rows={4}
          maxLength={2000}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Resolution note"
        />
      </label>

      {initial.rkn_notification_required ? (
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-gray-600">
            РКН уведомление (ФЗ-152 §17.1, 24ч/72ч)
          </span>
          <input
            type="datetime-local"
            value={rknNotifiedAt}
            onChange={(e) => setRknNotifiedAt(e.target.value)}
            className="w-64 rounded-md border border-gray-300 px-2 py-1 text-xs"
            aria-label="RKN notification timestamp"
          />
        </label>
      ) : null}

      {error ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900"
        >
          {error}
        </div>
      ) : null}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-ink hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? "Сохранение…" : "Сохранить"}
        </button>
        <a
          href="/admin/security-incidents"
          className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          Отмена
        </a>
      </div>
    </form>
  );
}

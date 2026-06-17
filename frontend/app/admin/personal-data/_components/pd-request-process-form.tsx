"use client";

/**
 * PD request process form (#256). Client-side mutation via PATCH
 * /admin/personal-data/requests/{id} (backend #232).
 *
 * Status options ограничены OpenAPI §processPersonalDataRequest enum:
 * IN_PROGRESS / COMPLETED / REJECTED. OVERDUE — auto-status (background
 * worker), NEW — initial status, не allowed в PATCH через эту форму.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  processPdRequest,
  type PdProcessInput,
  type PdProcessStatus,
} from "@/lib/api/admin-pd-requests";
import type { PersonalDataRequest } from "@/lib/api/types";

interface Props {
  initial: PersonalDataRequest;
}

const PROCESS_STATUSES: PdProcessStatus[] = ["IN_PROGRESS", "COMPLETED", "REJECTED"];

function defaultProcessStatus(s: string): PdProcessStatus {
  if (s === "IN_PROGRESS" || s === "COMPLETED" || s === "REJECTED") {
    return s;
  }
  return "IN_PROGRESS";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", { hour12: false });
}

export default function PdRequestProcessForm({ initial }: Props): JSX.Element {
  const router = useRouter();
  const [status, setStatus] = useState<PdProcessStatus>(
    defaultProcessStatus(initial.status),
  );
  const [resolutionNote, setResolutionNote] = useState(
    initial.resolution_note ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();

  const due = new Date(initial.due_at);
  const isOverdue =
    due < new Date() &&
    (initial.status === "NEW" || initial.status === "IN_PROGRESS");

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    const patch: PdProcessInput = { status };
    if (resolutionNote !== (initial.resolution_note ?? "")) {
      patch.resolution_note = resolutionNote || null;
    }
    try {
      await processPdRequest(initial.id, patch);
      router.push("/admin/personal-data");
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
          <dd className="font-mono">{initial.type}</dd>
          <dt className="text-gray-600">Текущий статус</dt>
          <dd className="font-mono">{initial.status}</dd>
          <dt className="text-gray-600">Subject</dt>
          <dd className="text-gray-900">
            {initial.subject_email ?? initial.subject_phone ?? initial.subject_id}
          </dd>
          <dt className="text-gray-600">Создана</dt>
          <dd>{formatDate(initial.created_at)}</dd>
          <dt className="text-gray-600">Срок (ФЗ-152 30д)</dt>
          <dd className={isOverdue ? "font-medium text-red-700" : "text-gray-900"}>
            {formatDate(initial.due_at)}
            {isOverdue ? " — просрочено" : ""}
          </dd>
          {initial.description ? (
            <>
              <dt className="text-gray-600">Описание</dt>
              <dd className="text-gray-900">{initial.description}</dd>
            </>
          ) : null}
        </dl>
      </div>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Новый статус</span>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as PdProcessStatus)}
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Process status"
        >
          {PROCESS_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
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
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? "Сохранение…" : "Сохранить"}
        </button>
        <a
          href="/admin/personal-data"
          className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          Отмена
        </a>
      </div>
    </form>
  );
}

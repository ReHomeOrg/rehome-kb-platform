"use client";

/**
 * Lifecycle actions (#192) — кнопки Активировать / Приостановить.
 *
 * Backend (ADR-0014, Slice 2):
 *  - POST /activate: для DRAFT/PENDING_REVIEW/SUSPENDED → ACTIVE
 *  - POST /suspend: для ACTIVE → SUSPENDED, требует reason
 *
 * Подсказка для UX: кнопки рендерятся условно по `status`. Suspend
 * раскрывает inline form (reason textarea + опциональный `until`).
 * После успеха — router.refresh() (страница ре-fetch'ит detail/list).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  activateCollaborator,
  suspendCollaborator,
} from "@/lib/api/collaborators";
import type { CollaboratorStatus } from "@/lib/api/types";

interface Props {
  id: string;
  status: CollaboratorStatus;
  /** Compact mode — короче кнопки, для inline в таблице очереди. */
  compact?: boolean;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown } | null;
    if (typeof body?.detail === "string") {
      return `${err.status}: ${body.detail}`;
    }
    return `${err.status}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Ошибка";
}

export default function LifecycleActions({
  id,
  status,
  compact = false,
}: Props): JSX.Element | null {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suspendOpen, setSuspendOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");

  const canActivate =
    status === "DRAFT" || status === "PENDING_REVIEW" || status === "SUSPENDED";
  const canSuspend = status === "ACTIVE";

  if (!canActivate && !canSuspend) {
    return null;
  }

  async function onActivate(): Promise<void> {
    if (pending) return;
    setError(null);
    setPending(true);
    try {
      await activateCollaborator(id);
      router.refresh();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPending(false);
    }
  }

  async function onSuspendSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (pending) return;
    if (!reason.trim()) {
      setError("Reason обязательна для приостановки");
      return;
    }
    setError(null);
    setPending(true);
    try {
      await suspendCollaborator(id, {
        reason: reason.trim(),
        until: until || null,
      });
      setSuspendOpen(false);
      setReason("");
      setUntil("");
      router.refresh();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPending(false);
    }
  }

  const btnBase = compact
    ? "rounded-md border px-2 py-1 text-xs font-medium disabled:opacity-50"
    : "rounded-md border px-3 py-1.5 text-sm font-medium disabled:opacity-50";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {canActivate ? (
          <button
            type="button"
            onClick={onActivate}
            disabled={pending}
            className={`${btnBase} border-green-300 bg-green-50 text-green-800 hover:bg-green-100`}
          >
            {pending ? "…" : "Активировать"}
          </button>
        ) : null}
        {canSuspend ? (
          <button
            type="button"
            onClick={() => {
              setSuspendOpen((v) => !v);
              setError(null);
            }}
            disabled={pending}
            className={`${btnBase} border-orange-300 bg-orange-50 text-orange-800 hover:bg-orange-100`}
          >
            {suspendOpen ? "Отмена" : "Приостановить"}
          </button>
        ) : null}
      </div>

      {suspendOpen ? (
        <form
          onSubmit={onSuspendSubmit}
          className="flex flex-col gap-2 rounded-md border border-orange-200 bg-orange-50/40 p-3"
        >
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-gray-700">
              Причина <span className="text-red-700">*</span>
            </span>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              maxLength={500}
              required
              placeholder="например: жалобы клиентов, проверка СЛА"
              className="rounded-md border border-gray-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-gray-700">
              До (опционально)
            </span>
            <input
              type="datetime-local"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              className="rounded-md border border-gray-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="submit"
            disabled={pending}
            className="self-start rounded-md bg-orange-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-800 disabled:opacity-50"
          >
            {pending ? "Приостанавливаем…" : "Подтвердить приостановку"}
          </button>
        </form>
      ) : null}

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}

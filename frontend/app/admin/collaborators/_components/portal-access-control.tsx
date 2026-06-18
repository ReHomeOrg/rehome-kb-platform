"use client";

/**
 * Portal access change control (ADR-0015 §5, ТЗ §10.8).
 *
 * STAFF+ меняет уровень кабинета коллаборанта: NONE / LIGHT / FULL.
 * - **Повышение** (raising tier) — backend требует reason (ТЗ §10.8.1).
 *   UI делает reason обязательным до отправки.
 * - **Понижение** — reason optional.
 *
 * После успеха router.refresh() — detail-страница ре-fetch'ит данные.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { changePortalAccess } from "@/lib/api/collaborators";
import type { CollaboratorPortalAccessLevel } from "@/lib/api/types";

interface Props {
  id: string;
  current: CollaboratorPortalAccessLevel;
}

const LEVELS: { value: CollaboratorPortalAccessLevel; label: string; rank: number }[] = [
  { value: "NONE", label: "NONE — без кабинета", rank: 0 },
  { value: "LIGHT", label: "LIGHT — просмотр заявок", rank: 1 },
  { value: "FULL", label: "FULL — полный кабинет", rank: 2 },
];

function rankOf(level: CollaboratorPortalAccessLevel): number {
  return LEVELS.find((l) => l.value === level)?.rank ?? 0;
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

export default function PortalAccessControl({
  id,
  current,
}: Props): JSX.Element {
  const router = useRouter();
  const [target, setTarget] = useState<CollaboratorPortalAccessLevel>(current);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPromotion = rankOf(target) > rankOf(current);
  const isChange = target !== current;
  const reasonRequired = isPromotion;

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (!isChange || pending) return;
    if (reasonRequired && !reason.trim()) {
      setError("Reason обязательна при повышении уровня кабинета");
      return;
    }
    setError(null);
    setPending(true);
    try {
      await changePortalAccess(id, {
        portal_access_level: target,
        reason: reason.trim() || null,
      });
      setReason("");
      router.refresh();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="rounded-md border border-gray-200 p-4">
      <h2 className="text-sm font-medium text-gray-700">Кабинет коллаборанта</h2>
      <p className="mt-1 text-xs text-gray-500">
        Текущий уровень:{" "}
        <code className="rounded bg-gray-100 px-1.5 py-0.5">{current}</code>.
        Повышение требует указания причины (журналируется в audit_log,
        ADR-0015 §5).
      </p>
      <form onSubmit={onSubmit} className="mt-3 flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Новый уровень</span>
          <select
            value={target}
            onChange={(e) => {
              setTarget(e.target.value as CollaboratorPortalAccessLevel);
              setError(null);
            }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            {LEVELS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Причина{" "}
            {reasonRequired ? (
              <span className="text-red-700">*</span>
            ) : (
              <span className="text-xs text-gray-500">(optional при понижении)</span>
            )}
          </span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            maxLength={500}
            placeholder={
              reasonRequired
                ? "например: подписан расширенный SLA, активирован API"
                : "например: пауза до подтверждения документов"
            }
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        {error ? (
          <p
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700"
          >
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={!isChange || pending}
          className="self-start rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-ink hover:bg-brand-hover disabled:opacity-50"
        >
          {pending ? "Применяем…" : isChange ? "Применить" : "Без изменений"}
        </button>
      </form>
    </section>
  );
}

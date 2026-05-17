"use client";

/**
 * Premises ↔ Collaborators junction section (ТЗ §10.6, Slice 5).
 *
 * Renders list of коллаборантов, обслуживающих этот объект, plus
 * STAFF-only assign / remove controls. Scope visibility наследуется
 * от backend'а (guest видит только D-группу, STAFF — все).
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  assignCollaborator,
  listPremisesCollaborators,
  removeCollaborator,
} from "@/lib/api/premises-collaborators";
import type { PremisesCollaboratorRow } from "@/lib/api/types";

interface Props {
  premisesId: string;
  /** Show assign form + remove buttons. Backend всё равно проверяет scope. */
  canManage: boolean;
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

export default function CollaboratorsSection({
  premisesId,
  canManage,
}: Props): JSX.Element {
  const [rows, setRows] = useState<PremisesCollaboratorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showAssign, setShowAssign] = useState(false);
  const [collabId, setCollabId] = useState("");
  const [role, setRole] = useState("");
  const [priority, setPriority] = useState("1");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function reload(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const resp = await listPremisesCollaborators(premisesId);
      setRows(resp.data);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [premisesId]);

  async function onAssign(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (submitting) return;
    setSubmitError(null);
    const prio = Number(priority);
    if (!Number.isFinite(prio) || prio < 1 || prio > 99) {
      setSubmitError("Приоритет — целое число 1..99");
      return;
    }
    setSubmitting(true);
    try {
      await assignCollaborator(premisesId, {
        collaborator_id: collabId.trim(),
        role: role.trim(),
        priority: prio,
        notes: notes.trim() || null,
      });
      setCollabId("");
      setRole("");
      setPriority("1");
      setNotes("");
      setShowAssign(false);
      await reload();
    } catch (err) {
      setSubmitError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function onRemove(row: PremisesCollaboratorRow): Promise<void> {
    const confirmed = window.confirm(
      `Убрать назначение ${row.collaborator.brand_name ?? row.collaborator_id} (${row.role})?`,
    );
    if (!confirmed) return;
    try {
      await removeCollaborator(premisesId, row.collaborator_id, row.role);
      await reload();
    } catch (err) {
      setError(describeError(err));
    }
  }

  return (
    <section className="rounded-md border border-gray-200 p-4">
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-gray-700">
          Коллаборанты, обслуживающие объект
        </h2>
        {canManage ? (
          <button
            type="button"
            onClick={() => {
              setShowAssign((v) => !v);
              setSubmitError(null);
            }}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50"
          >
            {showAssign ? "Отмена" : "+ Назначить"}
          </button>
        ) : null}
      </header>

      {loading ? (
        <p className="mt-3 text-xs text-gray-500">Загружаем…</p>
      ) : error ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700"
        >
          {error}
        </p>
      ) : rows.length === 0 ? (
        <p className="mt-3 text-xs text-gray-500">
          Назначений нет. {canManage ? "Используйте \"+ Назначить\" для добавления." : ""}
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-gray-100">
          {rows.map((r) => (
            <li
              key={r.id}
              className="flex items-start justify-between gap-3 py-2 text-sm"
            >
              <div>
                <p className="font-medium text-gray-900">
                  {r.collaborator.brand_name ?? r.collaborator_id.slice(0, 8)}
                </p>
                <p className="text-xs text-gray-500">
                  {r.role} · приоритет {r.priority}
                  {r.notes ? ` · ${r.notes}` : ""}
                </p>
              </div>
              {canManage ? (
                <button
                  type="button"
                  onClick={() => void onRemove(r)}
                  className="shrink-0 rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-800 hover:bg-red-100"
                >
                  Убрать
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {showAssign ? (
        <form
          onSubmit={onAssign}
          className="mt-4 flex flex-col gap-2 rounded-md border border-gray-200 bg-gray-50 p-3"
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">
                ID коллаборанта <span className="text-red-700">*</span>
              </span>
              <input
                type="text"
                value={collabId}
                onChange={(e) => setCollabId(e.target.value)}
                required
                placeholder="UUID"
                className="rounded-md border border-gray-300 px-2 py-1 text-xs font-mono"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">
                Role <span className="text-red-700">*</span>
              </span>
              <input
                type="text"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                required
                maxLength={50}
                placeholder="default_uk / emergency_water / plumber"
                className="rounded-md border border-gray-300 px-2 py-1 text-xs"
              />
            </label>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">Приоритет (1..99)</span>
              <input
                type="number"
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                min={1}
                max={99}
                className="rounded-md border border-gray-300 px-2 py-1 text-xs"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">Заметки</span>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                maxLength={2000}
                className="rounded-md border border-gray-300 px-2 py-1 text-xs"
              />
            </label>
          </div>
          {submitError ? (
            <p
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700"
            >
              {submitError}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={submitting}
            className="self-start rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {submitting ? "Сохраняем…" : "Назначить"}
          </button>
        </form>
      ) : null}
    </section>
  );
}

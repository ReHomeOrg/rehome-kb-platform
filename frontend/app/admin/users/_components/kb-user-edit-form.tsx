"use client";

/**
 * KB user edit form (#257) — PATCH role / status / permissions +
 * separate Deactivate button (DELETE /admin/users/{id}).
 *
 * Identity fields (email / full_name) — read-only (backend immutable
 * после create). Permissions edit — простой textarea с newline-split
 * (full permission editor — backlog).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  deactivateKbUser,
  patchKbUser,
  type KbUserPatchInput,
} from "@/lib/api/admin-users";
import type { KbUser, KbUserRole, KbUserStatus } from "@/lib/api/types";

interface Props {
  initial: KbUser;
}

const ROLES: KbUserRole[] = [
  "staff_support",
  "staff_legal",
  "staff_hr",
  "staff_admin",
];
const STATUSES: KbUserStatus[] = ["ACTIVE", "SUSPENDED", "ARCHIVED"];

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", { hour12: false });
}

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((v, i) => v === b[i]);
}

export default function KbUserEditForm({ initial }: Props): JSX.Element {
  const router = useRouter();
  const [role, setRole] = useState<KbUserRole>(initial.role);
  const [status, setStatus] = useState<KbUserStatus>(initial.status);
  const [permissionsText, setPermissionsText] = useState(
    initial.permissions.join("\n"),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();

  async function handleSave(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    const patch: KbUserPatchInput = {};
    if (role !== initial.role) patch.role = role;
    if (status !== initial.status) patch.status = status;
    const newPermissions = permissionsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!arraysEqual(newPermissions, initial.permissions)) {
      patch.permissions = newPermissions;
    }
    if (Object.keys(patch).length === 0) {
      setBusy(false);
      return;
    }
    try {
      await patchKbUser(initial.id, patch);
      router.push("/admin/users");
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

  async function handleDeactivate(): Promise<void> {
    if (
      !window.confirm(
        `Деактивировать ${initial.email}? Действие необратимо (status=ARCHIVED).`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      await deactivateKbUser(initial.id);
      router.push("/admin/users");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Ошибка ${e.status}: ${e.message}`);
      } else {
        setError("Не удалось деактивировать.");
      }
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSave} className="space-y-4">
      <div className="rounded-md border border-gray-200 bg-white p-4">
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <dt className="text-gray-600">ID</dt>
          <dd className="font-mono text-gray-900">{initial.id}</dd>
          <dt className="text-gray-600">Email</dt>
          <dd className="font-mono">{initial.email}</dd>
          <dt className="text-gray-600">Имя</dt>
          <dd className="text-gray-900">{initial.full_name}</dd>
          <dt className="text-gray-600">MFA</dt>
          <dd>
            {initial.mfa_enabled ? (
              <span className="text-green-700" aria-label="MFA enabled">
                ✓ включён
              </span>
            ) : (
              <span className="text-red-700" aria-label="MFA disabled">
                ✗ выключен
              </span>
            )}
          </dd>
          <dt className="text-gray-600">Создан</dt>
          <dd>{formatDate(initial.created_at)}</dd>
          <dt className="text-gray-600">Последний вход</dt>
          <dd>{formatDate(initial.last_login_at)}</dd>
        </dl>
      </div>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Role</span>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as KbUserRole)}
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Role"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Status</span>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as KbUserStatus)}
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Status"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">
          Permissions (по одной на строку)
        </span>
        <textarea
          value={permissionsText}
          onChange={(e) => setPermissionsText(e.target.value)}
          rows={4}
          maxLength={2000}
          className="rounded-md border border-gray-300 px-2 py-1 font-mono text-xs"
          aria-label="Permissions"
          placeholder="article.publish&#10;chat.escalate"
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

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          {busy ? "Сохранение…" : "Сохранить"}
        </button>
        <a
          href="/admin/users"
          className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          Отмена
        </a>
        {initial.status !== "ARCHIVED" ? (
          <button
            type="button"
            onClick={handleDeactivate}
            disabled={busy}
            className="ml-auto rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            Деактивировать
          </button>
        ) : null}
      </div>
    </form>
  );
}

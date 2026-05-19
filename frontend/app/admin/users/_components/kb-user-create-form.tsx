"use client";

/**
 * KB user create form (#260). POST /admin/users (backend #230).
 *
 * Backend enforces uniqueness on email (409 Conflict). MFA-enrollment
 * — backlog (отдельный flow после first login).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  createKbUser,
  type KbUserCreateInput,
} from "@/lib/api/admin-users";
import type { KbUserRole } from "@/lib/api/types";

const ROLES: KbUserRole[] = [
  "staff_support",
  "staff_legal",
  "staff_hr",
  "staff_admin",
];

export default function KbUserCreateForm(): JSX.Element {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<KbUserRole>("staff_support");
  const [permissionsText, setPermissionsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    if (!email.trim() || !fullName.trim()) {
      setError("Email + Имя обязательны.");
      setBusy(false);
      return;
    }
    const input: KbUserCreateInput = {
      email: email.trim(),
      full_name: fullName.trim(),
      role,
    };
    const permissions = permissionsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (permissions.length > 0) {
      input.permissions = permissions;
    }
    try {
      const created = await createKbUser(input);
      router.push(`/admin/users/${created.id}`);
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          setError("Пользователь с таким email уже существует.");
        } else {
          setError(`Ошибка ${e.status}: ${e.message}`);
        }
      } else {
        setError("Не удалось создать.");
      }
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Email *</span>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          maxLength={255}
          className="w-80 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Email"
          placeholder="user@rehome.one"
        />
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Полное имя *</span>
        <input
          type="text"
          required
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          maxLength={200}
          className="w-80 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Full name"
        />
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Role *</span>
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
        <span className="text-gray-600">
          Permissions (по одной на строку, optional)
        </span>
        <textarea
          value={permissionsText}
          onChange={(e) => setPermissionsText(e.target.value)}
          rows={3}
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

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          {busy ? "Создание…" : "Создать"}
        </button>
        <a
          href="/admin/users"
          className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          Отмена
        </a>
      </div>
    </form>
  );
}

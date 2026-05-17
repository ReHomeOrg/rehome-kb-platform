"use client";

/**
 * Group members management panel (ADR-0016 Slice 3 narrowed).
 *
 * Owner может add/remove member'ов. Non-owner — read-only.
 * Defensive: owner не может удалить себя (backend 403; UI скрывает
 * remove-кнопку для своего ряда).
 *
 * Stage 1.4 backlog: после add/remove потребуется re-wrap всех secret_keys
 * группы — для этого нужны backend additions (pubkey discovery,
 * add-wrap endpoint). Текущий PR membership change does NOT re-wrap.
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  addGroupMember,
  listGroupMembers,
  removeGroupMember,
  type VaultGroupMemberView,
  type VaultGroupView,
} from "@/lib/api/vault";

interface Props {
  groupId: string;
  group: VaultGroupView | null;
  currentUserId: string;
  onBack: () => void;
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

export default function GroupMembersPanel({
  groupId,
  group,
  currentUserId,
  onBack,
}: Props): JSX.Element {
  const [members, setMembers] = useState<VaultGroupMemberView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [addUserId, setAddUserId] = useState("");
  const [addRole, setAddRole] = useState<"owner" | "member">("member");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  async function reload(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const resp = await listGroupMembers(groupId);
      setMembers(resp.data);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupId]);

  const isOwner = members.some(
    (m) => m.user_id === currentUserId && m.role === "owner",
  );

  async function onAdd(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (adding) return;
    setAddError(null);
    if (!addUserId.trim()) {
      setAddError("Укажите user_id (UUID Keycloak'а)");
      return;
    }
    setAdding(true);
    try {
      await addGroupMember(groupId, {
        user_id: addUserId.trim(),
        role: addRole,
      });
      setAddUserId("");
      setAddRole("member");
      await reload();
    } catch (err) {
      setAddError(describeError(err));
    } finally {
      setAdding(false);
    }
  }

  async function onRemove(memberUserId: string): Promise<void> {
    const confirmed = window.confirm(
      "Удалить участника из группы? Re-wrap секретов группы — backlog.",
    );
    if (!confirmed) return;
    try {
      await removeGroupMember(groupId, memberUserId);
      await reload();
    } catch (err) {
      setError(describeError(err));
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="text-xs text-gray-600 hover:underline"
        >
          ← К списку групп
        </button>
      </div>
      <header>
        <h3 className="text-sm font-medium text-gray-700">
          {group?.name ?? "Группа"} — участники
        </h3>
        {group?.description ? (
          <p className="text-xs text-gray-500">{group.description}</p>
        ) : null}
      </header>

      <p className="rounded-md border border-yellow-200 bg-yellow-50 p-2 text-xs text-yellow-900">
        <strong>Caveat:</strong> добавление участника НЕ открывает ему
        доступ к existing секретам группы — для этого требуется re-wrap
        ключей под его pubkey (backend backlog, Stage 1.4).
      </p>

      {loading ? (
        <p className="text-xs text-gray-500">Загружаем…</p>
      ) : error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700"
        >
          {error}
        </p>
      ) : members.length === 0 ? (
        <p className="text-xs text-gray-500">Участников нет.</p>
      ) : (
        <ul className="divide-y divide-gray-100 rounded-md border border-gray-200">
          {members.map((m) => (
            <li
              key={m.user_id}
              className="flex items-center justify-between gap-3 p-3 text-sm"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-xs text-gray-900">
                  {m.user_id}
                </p>
                <p className="text-xs text-gray-500">
                  {m.role} · добавлен{" "}
                  {new Date(m.added_at).toLocaleDateString("ru-RU")}
                  {m.user_id === currentUserId ? " · это вы" : ""}
                </p>
              </div>
              {isOwner && m.user_id !== currentUserId ? (
                <button
                  type="button"
                  onClick={() => void onRemove(m.user_id)}
                  className="shrink-0 rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-800 hover:bg-red-100"
                >
                  Убрать
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {isOwner ? (
        <form
          onSubmit={onAdd}
          className="mt-2 flex flex-col gap-2 rounded-md border border-gray-200 bg-gray-50 p-3"
        >
          <h4 className="text-xs font-medium text-gray-700">
            Добавить участника
          </h4>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">
              User ID (Keycloak sub){" "}
              <span className="text-red-700">*</span>
            </span>
            <input
              type="text"
              value={addUserId}
              onChange={(e) => setAddUserId(e.target.value)}
              required
              placeholder="UUID"
              className="rounded-md border border-gray-300 px-2 py-1 text-xs font-mono"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">Роль</span>
            <select
              value={addRole}
              onChange={(e) =>
                setAddRole(e.target.value as "owner" | "member")
              }
              className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="member">member</option>
              <option value="owner">owner</option>
            </select>
          </label>
          {addError ? (
            <p
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700"
            >
              {addError}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={adding}
            className="self-start rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {adding ? "Добавляем…" : "Добавить"}
          </button>
        </form>
      ) : null}
    </div>
  );
}

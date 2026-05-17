"use client";

/**
 * Groups panel (ADR-0016 Slice 3 narrowed scope — management only).
 *
 * UI: список групп + создание + drill-down в group-members сборщик.
 *
 * Sharing existing secrets с группой пока **не реализован** — backend
 * gap: vault_groups не имеет own X25519 keypair, нет endpoint'а для
 * fetch pubkey другого user'а, нет endpoint'а для add-wrap-to-existing-secret.
 * Это будет адресовано отдельным backend epic'ом (см. PR описание).
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  createVaultGroup,
  listVaultGroups,
  type VaultGroupView,
} from "@/lib/api/vault";

import GroupMembersPanel from "./group-members-panel";

interface Props {
  currentUserId: string;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return `${err.status}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Ошибка";
}

export default function GroupsPanel({ currentUserId }: Props): JSX.Element {
  const [groups, setGroups] = useState<VaultGroupView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [createPending, setCreatePending] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reload(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const resp = await listVaultGroups();
      setGroups(resp.data);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function onCreate(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (createPending) return;
    setCreateError(null);
    if (!name.trim()) {
      setCreateError("Название обязательно");
      return;
    }
    setCreatePending(true);
    try {
      await createVaultGroup({
        name: name.trim(),
        description: description.trim() || null,
      });
      setName("");
      setDescription("");
      setShowCreate(false);
      await reload();
    } catch (err) {
      setCreateError(describeError(err));
    } finally {
      setCreatePending(false);
    }
  }

  if (selectedId) {
    const group = groups.find((g) => g.id === selectedId);
    return (
      <GroupMembersPanel
        group={group ?? null}
        groupId={selectedId}
        currentUserId={currentUserId}
        onBack={() => setSelectedId(null)}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">Группы доступа</h3>
        <button
          type="button"
          onClick={() => {
            setShowCreate((v) => !v);
            setCreateError(null);
          }}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-xs hover:bg-gray-50"
        >
          {showCreate ? "Отмена" : "+ Создать группу"}
        </button>
      </div>

      <p className="rounded-md border border-yellow-200 bg-yellow-50 p-2 text-xs text-yellow-900">
        <strong>Slice 3 scope:</strong> управление группами и членством.
        Шаринг секретов с группой требует доработок бэкенда — будет
        в следующем эпике.
      </p>

      {showCreate ? (
        <form
          onSubmit={onCreate}
          className="flex flex-col gap-2 rounded-md border border-gray-200 bg-gray-50 p-3"
        >
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">
              Название <span className="text-red-700">*</span>
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              required
              placeholder="backend-team / devops / management"
              className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">Описание</span>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
              placeholder="Доступ к prod БД и API-ключам"
              className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            />
          </label>
          {createError ? (
            <p
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700"
            >
              {createError}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={createPending}
            className="self-start rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {createPending ? "Создаём…" : "Создать"}
          </button>
        </form>
      ) : null}

      {loading ? (
        <p className="text-xs text-gray-500">Загружаем…</p>
      ) : error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700"
        >
          {error}
        </p>
      ) : groups.length === 0 ? (
        <p className="text-xs text-gray-500">
          Вы не состоите ни в одной группе. Создайте новую через «+ Создать
          группу».
        </p>
      ) : (
        <ul className="divide-y divide-gray-100 rounded-md border border-gray-200">
          {groups.map((g) => (
            <li
              key={g.id}
              className="flex items-center justify-between gap-3 p-3 text-sm hover:bg-gray-50"
            >
              <div className="min-w-0 flex-1">
                <button
                  type="button"
                  onClick={() => setSelectedId(g.id)}
                  className="block truncate text-left font-medium text-gray-900 hover:underline"
                >
                  {g.name}
                </button>
                {g.description ? (
                  <p className="text-xs text-gray-500">{g.description}</p>
                ) : null}
                <p className="text-xs text-gray-500">
                  создано {new Date(g.created_at).toLocaleDateString("ru-RU")}
                  {g.created_by === currentUserId ? " · вы создатель" : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedId(g.id)}
                className="shrink-0 rounded-md border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50"
              >
                Участники
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

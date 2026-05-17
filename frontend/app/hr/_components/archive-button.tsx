"use client";

/**
 * Archive (soft-delete) кнопка для employee card (#197, PZ §7.4).
 *
 * Soft-delete: archived_at marker. Запись хранится 50 лет (трудовые
 * договоры, ПЗ §7.4) — физического DROP не делаем. После успеха
 * router.push('/hr') (детальная страница вернёт 404 после archive).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { archiveEmployee } from "@/lib/api/hr";

interface Props {
  id: string;
}

export default function ArchiveButton({ id }: Props): JSX.Element {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onArchive(): Promise<void> {
    if (pending) return;
    setError(null);
    setPending(true);
    try {
      await archiveEmployee(id);
      router.push("/hr");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`${err.status}: ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : "Ошибка");
      }
      setPending(false);
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-sm font-medium text-red-800 hover:bg-red-100"
      >
        Архивировать
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-red-200 bg-red-50/40 p-3">
      <p className="text-xs text-red-900">
        Архивация скрывает карточку из активного списка. Данные сохраняются
        50 лет (ПЗ §7.4). Восстановление — через DB / отдельный admin
        endpoint.
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onArchive}
          disabled={pending}
          className="rounded-md bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-800 disabled:opacity-50"
        >
          {pending ? "Архивируем…" : "Подтвердить архивацию"}
        </button>
        <button
          type="button"
          onClick={() => {
            setConfirming(false);
            setError(null);
          }}
          disabled={pending}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-xs hover:bg-gray-50 disabled:opacity-50"
        >
          Отмена
        </button>
      </div>
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

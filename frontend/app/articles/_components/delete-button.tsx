"use client";

/**
 * Delete article (soft-delete на backend'е) с confirm-step.
 *
 * После успеха redirect /articles. Backend audit'ит operation (ACTION_ARTICLES_DELETED).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { deleteArticle } from "@/lib/api/articles";
import { ApiError } from "@/lib/api/client";

interface Props {
  slug: string;
}

export default function DeleteArticleButton({ slug }: Props): JSX.Element {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onDelete(): Promise<void> {
    if (pending) return;
    setError(null);
    setPending(true);
    try {
      await deleteArticle(slug);
      router.push("/articles");
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
        Удалить
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-red-200 bg-red-50/40 p-3">
      <p className="text-xs text-red-900">
        Статья будет soft-deleted (восстановление — через DB).
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onDelete}
          disabled={pending}
          className="rounded-md bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-800 disabled:opacity-50"
        >
          {pending ? "Удаляем…" : "Подтвердить"}
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

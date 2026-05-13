"use client";

/**
 * Webhooks list table (UI.7 #95).
 *
 * Каждая строка содержит test + delete buttons (Client). После mutate'а
 * вызывается `router.refresh()` для server-side re-fetch'а списка.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { deleteWebhook, testWebhook } from "@/lib/api/webhooks";
import type { Webhook } from "@/lib/api/types";

interface WebhooksTableProps {
  webhooks: Webhook[];
}

export default function WebhooksTable({
  webhooks,
}: WebhooksTableProps): JSX.Element {
  if (webhooks.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Нет активных подписок.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-gray-200">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left text-xs uppercase text-gray-600">
          <tr>
            <th className="px-3 py-2">URL</th>
            <th className="px-3 py-2">События</th>
            <th className="px-3 py-2">Last delivery</th>
            <th className="px-3 py-2">Создан</th>
            <th className="px-3 py-2 text-right">Действия</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {webhooks.map((wh) => (
            <WebhookRow key={wh.id} webhook={wh} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WebhookRow({ webhook }: { webhook: Webhook }): JSX.Element {
  const router = useRouter();
  const [testing, setTesting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function onTest(): Promise<void> {
    if (testing) return;
    setTesting(true);
    setMessage(null);
    try {
      const result = await testWebhook(webhook.id);
      setMessage(`Test delivery enqueued: ${result.delivery_id.slice(0, 8)}…`);
    } catch (err) {
      setMessage(
        err instanceof ApiError
          ? `Ошибка ${err.status}`
          : "Не удалось отправить test.",
      );
    } finally {
      setTesting(false);
    }
  }

  async function onDelete(): Promise<void> {
    if (deleting) return;
    if (!window.confirm("Удалить подписку?")) return;
    setDeleting(true);
    setMessage(null);
    try {
      await deleteWebhook(webhook.id);
      router.refresh();
    } catch (err) {
      setMessage(
        err instanceof ApiError
          ? `Ошибка ${err.status}`
          : "Не удалось удалить.",
      );
      setDeleting(false);
    }
  }

  const lastDelivery = webhook.last_delivery_at
    ? `${formatDate(webhook.last_delivery_at)} (${webhook.last_delivery_status ?? "?"})`
    : "—";

  return (
    <tr className="align-top">
      <td className="px-3 py-2">
        <code className="break-all text-xs">{webhook.url}</code>
        {webhook.description ? (
          <p className="mt-0.5 text-xs text-gray-500">{webhook.description}</p>
        ) : null}
      </td>
      <td className="px-3 py-2">
        <ul className="flex flex-wrap gap-1">
          {webhook.events.map((e) => (
            <li
              key={e}
              className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700"
            >
              {e}
            </li>
          ))}
        </ul>
      </td>
      <td className="px-3 py-2 text-xs text-gray-700">{lastDelivery}</td>
      <td className="px-3 py-2 text-xs text-gray-700">
        {formatDate(webhook.created_at)}
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-col items-end gap-1">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onTest}
              disabled={testing || deleting}
              className="rounded border border-gray-300 px-2 py-0.5 text-xs hover:bg-gray-50 disabled:opacity-50"
            >
              {testing ? "Test…" : "Test"}
            </button>
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting || testing}
              className="rounded border border-red-300 px-2 py-0.5 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
            >
              {deleting ? "…" : "Удалить"}
            </button>
          </div>
          {message ? <p className="text-xs text-gray-600">{message}</p> : null}
        </div>
      </td>
    </tr>
  );
}

function formatDate(iso: string): string {
  // Simple readable format; локализация — out of scope MVP.
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toISOString().slice(0, 16).replace("T", " ");
}

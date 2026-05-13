"use client";

/**
 * Webhook create form (UI.7 #95).
 *
 * URL + events (multi-checkbox) + optional description → POST. После
 * success — показывает secret + рекомендует сохранить его сейчас,
 * затем `router.refresh()` обновляет список.
 *
 * Текущий backend возвращает secret и при последующих GET (см.
 * `WebhookResponse.from_model`), но UX best practice — сохранять секрет
 * в момент создания, чтобы не светить его в дополнительных запросах.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { createWebhook } from "@/lib/api/webhooks";
import { WEBHOOK_EVENTS } from "@/lib/api/types";
import type { Webhook } from "@/lib/api/types";

export default function CreateForm(): JSX.Element {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<Set<string>>(new Set());
  const [description, setDescription] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Webhook | null>(null);

  function toggleEvent(event: string): void {
    setEvents((prev) => {
      const next = new Set(prev);
      if (next.has(event)) {
        next.delete(event);
      } else {
        next.add(event);
      }
      return next;
    });
  }

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (pending) return;
    setError(null);
    if (events.size === 0) {
      setError("Выберите хотя бы одно событие.");
      return;
    }
    setPending(true);
    try {
      const result = await createWebhook({
        url: url.trim(),
        events: Array.from(events),
        description: description.trim() || null,
      });
      setCreated(result);
      // Reset form fields для следующего create.
      setUrl("");
      setEvents(new Set());
      setDescription("");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as { detail?: string } | null;
        setError(body?.detail ?? `Ошибка ${err.status}`);
      } else {
        setError("Сбой сети. Попробуйте позже.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {created ? (
        <SecretBanner webhook={created} onDismiss={() => setCreated(null)} />
      ) : null}

      <form
        onSubmit={onSubmit}
        className="flex flex-col gap-3 rounded-md border border-gray-200 p-4"
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">URL</span>
          <input
            type="url"
            required
            placeholder="https://your-app.example.com/webhooks/kb"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5"
          />
        </label>

        <fieldset className="flex flex-col gap-1.5 text-sm">
          <legend className="font-medium">События</legend>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {WEBHOOK_EVENTS.map((event) => (
              <label key={event} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={events.has(event)}
                  onChange={() => toggleEvent(event)}
                />
                <code className="text-xs">{event}</code>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">
            Описание <span className="text-gray-500">(опционально)</span>
          </span>
          <input
            type="text"
            maxLength={500}
            placeholder="Например: prod billing handler"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5"
          />
        </label>

        {error ? <p className="text-sm text-red-600">{error}</p> : null}

        <div>
          <button
            type="submit"
            disabled={pending}
            className="rounded-md border border-gray-300 bg-white px-4 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            {pending ? "Создаём…" : "Создать webhook"}
          </button>
        </div>
      </form>
    </div>
  );
}

function SecretBanner({
  webhook,
  onDismiss,
}: {
  webhook: Webhook;
  onDismiss: () => void;
}): JSX.Element {
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm">
      <p className="font-medium text-amber-900">
        Webhook создан. Сохраните secret в безопасное место — он понадобится
        для верификации HMAC-подписи доставок.
      </p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-amber-900">
        <dt className="font-medium">ID</dt>
        <dd>
          <code className="break-all">{webhook.id}</code>
        </dd>
        <dt className="font-medium">Secret</dt>
        <dd>
          <code className="break-all rounded bg-amber-100 px-1 py-0.5">
            {webhook.secret}
          </code>
        </dd>
      </dl>
      <button
        type="button"
        onClick={onDismiss}
        className="mt-3 rounded-md border border-amber-400 bg-white px-3 py-1 text-amber-900 hover:bg-amber-100"
      >
        Я сохранил secret
      </button>
    </div>
  );
}

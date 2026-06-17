"use client";

/**
 * Premises create/edit form (#162, staff_admin).
 *
 * Минимальный набор identification fields + JSONB textarea для blocks.
 * Не валидирует JSONB shape — backend Pydantic это делает (422 →
 * error message).
 *
 * `slug` — read-only для edit mode (slug immutable post-create).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  PremisesCreateInput,
  PremisesPatchInput,
  createPremisesCard,
  patchPremisesCard,
} from "@/lib/api/premises";
import { ApiError } from "@/lib/api/client";
import type { PremisesStatus, PremisesView } from "@/lib/api/types";

import { jsonToString, parseJsonOrNull } from "./form-helpers";

interface Props {
  /** When provided — edit mode; иначе create. */
  initial?: PremisesView;
}

const STATUSES: PremisesStatus[] = ["DRAFT", "PUBLISHED", "RENTED", "ARCHIVED"];

export default function PremisesForm({ initial }: Props): JSX.Element {
  const router = useRouter();
  const isEdit = Boolean(initial);

  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [address, setAddress] = useState(initial?.address ?? "");
  const [status, setStatus] = useState<PremisesStatus>(
    (initial?.status as PremisesStatus) ?? "DRAFT",
  );
  const [internalCode, setInternalCode] = useState(initial?.internal_code ?? "");
  const [postalCode, setPostalCode] = useState(initial?.postal_code ?? "");
  const [cadastralNumber, setCadastralNumber] = useState(
    initial?.cadastral_number ?? "",
  );
  const [owner, setOwner] = useState(jsonToString(initial?.owner));
  const [financial, setFinancial] = useState(jsonToString(initial?.financial_data));

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);

    const ownerParsed = parseJsonOrNull(owner);
    if (typeof ownerParsed === "string") {
      setError(`owner: ${ownerParsed}`);
      return;
    }
    const financialParsed = parseJsonOrNull(financial);
    if (typeof financialParsed === "string") {
      setError(`financial_data: ${financialParsed}`);
      return;
    }

    setPending(true);
    try {
      if (isEdit && initial) {
        const patch: PremisesPatchInput = {
          address,
          status,
          internal_code: internalCode || null,
          postal_code: postalCode || null,
          cadastral_number: cadastralNumber || null,
          owner: ownerParsed ?? undefined,
          financial_data: financialParsed ?? undefined,
        };
        await patchPremisesCard(initial.slug, patch);
        router.push(`/premises/${initial.slug}`);
      } else {
        const input: PremisesCreateInput = {
          slug,
          address,
          status,
          internal_code: internalCode || null,
          postal_code: postalCode || null,
          cadastral_number: cadastralNumber || null,
          owner: ownerParsed ?? {},
          financial_data: financialParsed ?? {},
        };
        await createPremisesCard(input);
        router.push(`/premises/${slug}`);
      }
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as { detail?: unknown };
        setError(
          typeof body?.detail === "string"
            ? `${err.status}: ${body.detail}`
            : `${err.status}: ${err.message}`,
        );
      } else {
        setError(err instanceof Error ? err.message : "Ошибка");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Slug{" "}
            <span className="text-xs text-gray-500">
              (lowercase, цифры, дефисы)
            </span>
          </span>
          <input
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            pattern="[a-z0-9\-]+"
            minLength={1}
            maxLength={200}
            required
            disabled={isEdit}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:bg-gray-100"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Статус</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as PremisesStatus)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">Адрес</span>
        <input
          type="text"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          maxLength={500}
          required
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Внутр. код</span>
          <input
            type="text"
            value={internalCode}
            onChange={(e) => setInternalCode(e.target.value)}
            maxLength={64}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Индекс</span>
          <input
            type="text"
            value={postalCode}
            onChange={(e) => setPostalCode(e.target.value)}
            maxLength={16}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Кадастр. №</span>
          <input
            type="text"
            value={cadastralNumber}
            onChange={(e) => setCadastralNumber(e.target.value)}
            maxLength={64}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Owner (JSON object){" "}
          <span className="text-xs text-gray-500">
            например: <code>{`{"name": "Иванов И.И.", "phone": "+79991234567"}`}</code>
          </span>
        </span>
        <textarea
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          rows={4}
          className="rounded-md border border-gray-300 px-3 py-1.5 font-mono text-xs"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Financial data (JSON object)
        </span>
        <textarea
          value={financial}
          onChange={(e) => setFinancial(e.target.value)}
          rows={4}
          className="rounded-md border border-gray-300 px-3 py-1.5 font-mono text-xs"
        />
      </label>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </p>
      ) : null}

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={pending}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover disabled:opacity-50"
        >
          {pending ? "Сохраняем…" : isEdit ? "Сохранить" : "Создать"}
        </button>
        <button
          type="button"
          onClick={() => router.back()}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm hover:bg-gray-50"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}

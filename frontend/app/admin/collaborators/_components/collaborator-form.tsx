"use client";

/**
 * Collaborator create/edit form (#184, ADR-0014).
 *
 * Минимальный набор identification fields + JSONB textarea для contacts/
 * financial_terms/sla/api_integration/counterparty_check. На validation
 * (type ↔ financial_group invariant, ТЗ §10.3) полагаемся на backend
 * Pydantic (422 → error message).
 *
 * `id` — read-only для edit mode (UUID immutable post-create).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  createCollaborator,
  patchCollaborator,
  type CollaboratorCreateInput,
  type CollaboratorPatchInput,
} from "@/lib/api/collaborators";
import type {
  CollaboratorAdmin,
  CollaboratorFinancialGroup,
  CollaboratorInternal,
  CollaboratorStatus,
  CollaboratorType,
} from "@/lib/api/types";

interface Props {
  /** When provided — edit mode; иначе create. */
  initial?: CollaboratorInternal | CollaboratorAdmin;
}

const TYPES: CollaboratorType[] = [
  "management_company",
  "emergency_service",
  "repair_handyman",
  "cleaning",
  "moving",
  "key_delivery",
  "insurance",
  "payment_partner",
  "kyc_provider",
  "edo_provider",
  "sms_voice",
  "it_infrastructure",
  "legal_consultant",
  "other",
];

const STATUSES: CollaboratorStatus[] = [
  "DRAFT",
  "PENDING_REVIEW",
  "ACTIVE",
  "SUSPENDED",
  "ARCHIVED",
];

function jsonToString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 2);
}

function parseJsonOrNull(s: string): Record<string, unknown> | string | null {
  const trimmed = s.trim();
  if (!trimmed) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return "ожидается JSON object {}";
    }
    return parsed as Record<string, unknown>;
  } catch (e) {
    return e instanceof Error ? e.message : "невалидный JSON";
  }
}

function parseJsonArrayOrNull(
  s: string,
): Array<Record<string, unknown>> | string | null {
  const trimmed = s.trim();
  if (!trimmed) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) {
      return "ожидается JSON array []";
    }
    return parsed as Array<Record<string, unknown>>;
  } catch (e) {
    return e instanceof Error ? e.message : "невалидный JSON";
  }
}

export default function CollaboratorForm({ initial }: Props): JSX.Element {
  const router = useRouter();
  const isEdit = Boolean(initial);

  const [name, setName] = useState(initial?.name ?? "");
  const [brandName, setBrandName] = useState(initial?.brand_name ?? "");
  const [type, setType] = useState<CollaboratorType>(
    initial?.type ?? "management_company",
  );
  const [financialGroup, setFinancialGroup] = useState<
    CollaboratorFinancialGroup | ""
  >(initial?.financial_group ?? "");
  const [status, setStatus] = useState<CollaboratorStatus>(
    initial?.status ?? "DRAFT",
  );
  const [serviceArea, setServiceArea] = useState(initial?.service_area ?? "");
  const [workingHours, setWorkingHours] = useState(
    initial?.working_hours ?? "",
  );
  const [website, setWebsite] = useState(initial?.website ?? "");
  const [responsibleInternal, setResponsibleInternal] = useState(
    initial?.responsible_internal ?? "",
  );
  const [inn, setInn] = useState(initial?.inn ?? "");
  const [ogrn, setOgrn] = useState(initial?.ogrn ?? "");
  const [kpp, setKpp] = useState(initial?.kpp ?? "");
  const [contacts, setContacts] = useState(jsonToString(initial?.contacts));
  const [financialTerms, setFinancialTerms] = useState(
    jsonToString(initial?.financial_terms),
  );
  const [sla, setSla] = useState(jsonToString(initial?.sla));
  const [counterpartyCheck, setCounterpartyCheck] = useState(
    jsonToString(initial?.counterparty_check),
  );

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);

    const contactsParsed = parseJsonArrayOrNull(contacts);
    if (typeof contactsParsed === "string") {
      setError(`contacts: ${contactsParsed}`);
      return;
    }
    const financialTermsParsed = parseJsonOrNull(financialTerms);
    if (typeof financialTermsParsed === "string") {
      setError(`financial_terms: ${financialTermsParsed}`);
      return;
    }
    const slaParsed = parseJsonOrNull(sla);
    if (typeof slaParsed === "string") {
      setError(`sla: ${slaParsed}`);
      return;
    }
    const counterpartyCheckParsed = parseJsonOrNull(counterpartyCheck);
    if (typeof counterpartyCheckParsed === "string") {
      setError(`counterparty_check: ${counterpartyCheckParsed}`);
      return;
    }

    setPending(true);
    try {
      if (isEdit && initial) {
        const patch: CollaboratorPatchInput = {
          name,
          brand_name: brandName || null,
          type,
          financial_group: financialGroup || undefined,
          status,
          service_area: serviceArea,
          working_hours: workingHours || null,
          website: website || null,
          responsible_internal: responsibleInternal || null,
          inn: inn || null,
          ogrn: ogrn || null,
          kpp: kpp || null,
          contacts: contactsParsed ?? undefined,
          financial_terms: financialTermsParsed ?? undefined,
          sla: slaParsed ?? undefined,
          counterparty_check: counterpartyCheckParsed ?? undefined,
        };
        await patchCollaborator(initial.id, patch);
        router.push(`/admin/collaborators/${encodeURIComponent(initial.id)}`);
      } else {
        const input: CollaboratorCreateInput = {
          name,
          brand_name: brandName || null,
          type,
          financial_group: financialGroup || undefined,
          status,
          service_area: serviceArea,
          working_hours: workingHours || null,
          website: website || null,
          responsible_internal: responsibleInternal || null,
          inn: inn || null,
          ogrn: ogrn || null,
          kpp: kpp || null,
          contacts: contactsParsed ?? [],
          financial_terms: financialTermsParsed ?? {},
          sla: slaParsed ?? {},
          counterparty_check: counterpartyCheckParsed ?? {},
        };
        const created = await createCollaborator(input);
        router.push(`/admin/collaborators/${encodeURIComponent(created.id)}`);
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
            Юр. название <span className="text-xs text-gray-500">(обязательно)</span>
          </span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            minLength={1}
            maxLength={500}
            required
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Бренд (если отличается)</span>
          <input
            type="text"
            value={brandName}
            onChange={(e) => setBrandName(e.target.value)}
            maxLength={200}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Тип</span>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as CollaboratorType)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Финансовая группа{" "}
            <span className="text-xs text-gray-500">
              (auto для type≠other)
            </span>
          </span>
          <select
            value={financialGroup}
            onChange={(e) =>
              setFinancialGroup(e.target.value as CollaboratorFinancialGroup | "")
            }
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            <option value="">auto</option>
            <option value="A">A — мы платим</option>
            <option value="B">B — через нас + комиссия</option>
            <option value="C">C — реферальная</option>
            <option value="D">D — бесплатный контакт</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Статус</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as CollaboratorStatus)}
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
        <span className="font-medium text-gray-700">География работы</span>
        <input
          type="text"
          value={serviceArea}
          onChange={(e) => setServiceArea(e.target.value)}
          maxLength={500}
          required
          placeholder="например, Москва, ЦАО или вся РФ"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Часы работы</span>
          <input
            type="text"
            value={workingHours}
            onChange={(e) => setWorkingHours(e.target.value)}
            maxLength={200}
            placeholder="24/7 или будни 9-18 МСК"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Сайт</span>
          <input
            type="text"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            maxLength={500}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Отв. сотрудник</span>
          <input
            type="text"
            value={responsibleInternal}
            onChange={(e) => setResponsibleInternal(e.target.value)}
            maxLength={200}
            placeholder="Иванов И.И."
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">ИНН</span>
          <input
            type="text"
            value={inn}
            onChange={(e) => setInn(e.target.value)}
            maxLength={20}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">ОГРН</span>
          <input
            type="text"
            value={ogrn}
            onChange={(e) => setOgrn(e.target.value)}
            maxLength={20}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">КПП</span>
          <input
            type="text"
            value={kpp}
            onChange={(e) => setKpp(e.target.value)}
            maxLength={20}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Контакты (JSON array){" "}
          <span className="text-xs text-gray-500">
            например: <code>{`[{"phone":"+7...","emergency_channel":true}]`}</code>
          </span>
        </span>
        <textarea
          value={contacts}
          onChange={(e) => setContacts(e.target.value)}
          rows={4}
          className="rounded-md border border-gray-300 px-3 py-1.5 font-mono text-xs"
        />
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Financial terms (JSON)</span>
          <textarea
            value={financialTerms}
            onChange={(e) => setFinancialTerms(e.target.value)}
            rows={3}
            className="rounded-md border border-gray-300 px-3 py-1.5 font-mono text-xs"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">SLA (JSON)</span>
          <textarea
            value={sla}
            onChange={(e) => setSla(e.target.value)}
            rows={3}
            className="rounded-md border border-gray-300 px-3 py-1.5 font-mono text-xs"
          />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Counterparty check (JSON){" "}
          <span className="text-xs text-gray-500">
            например: <code>{`{"result":"CLEAN","checked_at":"2026-05-16"}`}</code>
          </span>
        </span>
        <textarea
          value={counterpartyCheck}
          onChange={(e) => setCounterpartyCheck(e.target.value)}
          rows={3}
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
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-ink hover:bg-brand-hover disabled:opacity-50"
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

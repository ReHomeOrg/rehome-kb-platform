"use client";

/**
 * Employee create/edit form (#197, PZ §7.1).
 *
 * Минимальный набор fields для Stage 1 (full_name, position, department,
 * hire_date, status, personnel_number) + JSONB textarea для contact_info /
 * notes. Encryption ПДн (паспорт, ИНН, СНИЛС) — отдельный Stage 2 epic.
 *
 * Edit mode передаёт `initial`; UI отображает full_name disabled в edit
 * (логика "переименовать сотрудника" редкая и через смену записи).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  createEmployee,
  patchEmployee,
  type HrEmployeeCreateInput,
  type HrEmployeePatchInput,
} from "@/lib/api/hr";
import type { EmployeeStatus, HrEmployee } from "@/lib/api/types";

interface Props {
  initial?: HrEmployee;
}

const STATUSES: { value: EmployeeStatus; label: string }[] = [
  { value: "ACTIVE", label: "ACTIVE — работает" },
  { value: "ON_LEAVE", label: "ON_LEAVE — в отпуске / на больничном" },
  { value: "TERMINATED", label: "TERMINATED — уволен" },
];

function jsonToString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object" && !Object.keys(v as object).length) return "";
  return JSON.stringify(v, null, 2);
}

function parseJsonOrError(s: string): Record<string, unknown> | string | null {
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

export default function EmployeeForm({ initial }: Props): JSX.Element {
  const router = useRouter();
  const isEdit = Boolean(initial);

  const [fullName, setFullName] = useState(initial?.full_name ?? "");
  const [position, setPosition] = useState(initial?.position ?? "");
  const [department, setDepartment] = useState(initial?.department ?? "");
  const [hireDate, setHireDate] = useState(initial?.hire_date ?? "");
  const [terminationDate, setTerminationDate] = useState(
    initial?.termination_date ?? "",
  );
  const [status, setStatus] = useState<EmployeeStatus>(
    (initial?.status as EmployeeStatus) ?? "ACTIVE",
  );
  const [personnelNumber, setPersonnelNumber] = useState(
    initial?.personnel_number ?? "",
  );
  const [contactInfo, setContactInfo] = useState(
    jsonToString(initial?.contact_info),
  );
  const [notes, setNotes] = useState(jsonToString(initial?.notes));

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);

    const contactParsed = parseJsonOrError(contactInfo);
    if (typeof contactParsed === "string") {
      setError(`contact_info: ${contactParsed}`);
      return;
    }
    const notesParsed = parseJsonOrError(notes);
    if (typeof notesParsed === "string") {
      setError(`notes: ${notesParsed}`);
      return;
    }

    if (status === "TERMINATED" && !terminationDate) {
      setError("При статусе TERMINATED укажите дату увольнения");
      return;
    }

    setPending(true);
    try {
      if (isEdit && initial) {
        const patch: HrEmployeePatchInput = {
          full_name: fullName,
          position,
          department: department || null,
          hire_date: hireDate,
          termination_date: terminationDate || null,
          status,
          personnel_number: personnelNumber || null,
          contact_info: contactParsed ?? {},
          notes: notesParsed ?? {},
        };
        const updated = await patchEmployee(initial.id, patch);
        router.push(`/hr/${encodeURIComponent(updated.id)}`);
      } else {
        const input: HrEmployeeCreateInput = {
          full_name: fullName,
          position,
          department: department || null,
          hire_date: hireDate,
          termination_date: terminationDate || null,
          status,
          personnel_number: personnelNumber || null,
          contact_info: contactParsed ?? {},
          notes: notesParsed ?? {},
        };
        const created = await createEmployee(input);
        router.push(`/hr/${encodeURIComponent(created.id)}`);
      }
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as { detail?: unknown } | null;
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
            ФИО <span className="text-red-700">*</span>
          </span>
          <input
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            minLength={1}
            maxLength={200}
            required
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Должность <span className="text-red-700">*</span>
          </span>
          <input
            type="text"
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            minLength={1}
            maxLength={200}
            required
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Подразделение</span>
          <input
            type="text"
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            maxLength={200}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Табельный №</span>
          <input
            type="text"
            value={personnelNumber}
            onChange={(e) => setPersonnelNumber(e.target.value)}
            maxLength={32}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Дата приёма <span className="text-red-700">*</span>
          </span>
          <input
            type="date"
            value={hireDate}
            onChange={(e) => setHireDate(e.target.value)}
            required
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Дата увольнения</span>
          <input
            type="date"
            value={terminationDate}
            onChange={(e) => setTerminationDate(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Статус</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as EmployeeStatus)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Контакты (JSON object){" "}
          <span className="text-xs text-gray-500">
            например: <code>{`{"phone":"+7...","email":"...","emergency":{...}}`}</code>
          </span>
        </span>
        <textarea
          value={contactInfo}
          onChange={(e) => setContactInfo(e.target.value)}
          rows={4}
          className="rounded-md border border-gray-300 px-3 py-1.5 font-mono text-xs"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Заметки HR (JSON object){" "}
          <span className="text-xs text-gray-500">внутренние, sensitive</span>
        </span>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
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

"use client";

/**
 * Document filters (UI.5 #83) — Client Component с URL state.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

interface DocumentFiltersProps {
  initial: {
    category: string;
    status: string;
    related_entity: string;
  };
}

const CATEGORIES = [
  { value: "", label: "Все категории" },
  { value: "A", label: "A — публичные документы пользователей" },
  { value: "B", label: "B — заключённые договоры" },
  { value: "C", label: "C — договоры с подрядчиками" },
  { value: "D", label: "D — внутренние" },
  { value: "E", label: "E — регуляторы" },
  { value: "F", label: "F — шаблоны" },
];

const STATUSES = [
  { value: "", label: "Все статусы" },
  { value: "DRAFT", label: "DRAFT" },
  { value: "ACTIVE", label: "ACTIVE" },
  { value: "EXPIRED", label: "EXPIRED" },
  { value: "CANCELLED", label: "CANCELLED" },
];

export default function DocumentFilters({
  initial,
}: DocumentFiltersProps): JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [category, setCategory] = useState(initial.category);
  const [status, setStatus] = useState(initial.status);
  const [related, setRelated] = useState(initial.related_entity);

  function onSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const params = new URLSearchParams(searchParams.toString());
    params.delete("cursor");
    if (category) params.set("category", category);
    else params.delete("category");
    if (status) params.set("status", status);
    else params.delete("status");
    if (related) params.set("related_entity", related);
    else params.delete("related_entity");
    const qs = params.toString();
    router.push(`/documents${qs ? "?" + qs : ""}`);
  }

  return (
    <form
      onSubmit={onSubmit}
      className="grid grid-cols-1 gap-3 rounded-md border border-gray-200 bg-gray-50 p-4 sm:grid-cols-3"
    >
      <label className="flex flex-col text-sm">
        <span className="text-gray-700">Категория</span>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="mt-1 rounded border border-gray-300 px-2 py-1"
        >
          {CATEGORIES.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-sm">
        <span className="text-gray-700">Статус</span>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="mt-1 rounded border border-gray-300 px-2 py-1"
        >
          {STATUSES.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-sm">
        <span className="text-gray-700">Связанная сущность</span>
        <input
          type="text"
          value={related}
          onChange={(e) => setRelated(e.target.value)}
          placeholder="user:abc-123"
          className="mt-1 rounded border border-gray-300 px-2 py-1"
        />
      </label>
      <div className="sm:col-span-3 flex justify-end">
        <button
          type="submit"
          className="rounded-md bg-gray-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
        >
          Применить
        </button>
      </div>
    </form>
  );
}

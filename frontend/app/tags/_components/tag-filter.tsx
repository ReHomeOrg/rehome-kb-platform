"use client";

/**
 * Tag filter form (UI.3 #79) — Client Component.
 *
 * Substring filter — отправляет на `/tags?q=...`.
 */

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

export default function TagFilter({
  initial = "",
}: {
  initial?: string;
}): JSX.Element {
  const router = useRouter();
  const [q, setQ] = useState(initial);

  function onSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const trimmed = q.trim();
    if (!trimmed) {
      router.push("/tags");
      return;
    }
    router.push(`/tags?q=${encodeURIComponent(trimmed)}`);
  }

  return (
    <form onSubmit={onSubmit} className="flex gap-2">
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="фильтр по подстроке"
        className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
      />
      <button
        type="submit"
        className="rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-hover"
      >
        Найти
      </button>
    </form>
  );
}

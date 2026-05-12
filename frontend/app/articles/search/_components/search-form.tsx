"use client";

/**
 * Search form (Client Component) — submit делает push в URL.
 */

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

export default function SearchForm({
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
      router.push("/articles/search");
      return;
    }
    router.push(`/articles/search?q=${encodeURIComponent(trimmed)}`);
  }

  return (
    <form onSubmit={onSubmit} className="flex gap-2">
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Например: сервисный платёж"
        className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
      />
      <button
        type="submit"
        className="rounded-md bg-gray-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
      >
        Найти
      </button>
    </form>
  );
}

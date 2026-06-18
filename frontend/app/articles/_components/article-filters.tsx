"use client";

/**
 * Filter form для /articles (UI.2 #77) — Client Component.
 *
 * Принимает текущие filters (из URL search params), позволяет менять,
 * на submit делает `router.push(/articles?...)` — URL state pattern.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

export interface CategoryOption {
  /** Значение фильтра — `slug` (бэкенд матчит `Article.category == slug`). */
  slug: string;
  /** Подпись для пользователя. */
  title: string;
}

interface ArticleFiltersProps {
  initial: {
    category: string;
    audience: string;
    language: string;
    tags: string;
  };
  /** Категории для выпадающего списка (value=slug, label=title). */
  categories: CategoryOption[];
  /** Аудитория/язык — фильтры только для админ-стаффа. */
  isStaffAdmin: boolean;
}

export default function ArticleFilters({
  initial,
  categories,
  isStaffAdmin,
}: ArticleFiltersProps): JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [category, setCategory] = useState(initial.category);
  const [audience, setAudience] = useState(initial.audience);
  const [language, setLanguage] = useState(initial.language);
  const [tags, setTags] = useState(initial.tags);

  function onSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const params = new URLSearchParams(searchParams.toString());
    // Сбрасываем cursor при изменении фильтров (новый список).
    params.delete("cursor");
    if (category) params.set("category", category);
    else params.delete("category");
    if (audience) params.set("audience", audience);
    else params.delete("audience");
    if (language) params.set("language", language);
    else params.delete("language");
    if (tags) params.set("tags", tags);
    else params.delete("tags");
    router.push(`/articles${params.toString() ? "?" + params.toString() : ""}`);
  }

  return (
    <form
      onSubmit={onSubmit}
      className="grid grid-cols-1 gap-3 rounded-md border border-gray-200 bg-gray-50 p-4 sm:grid-cols-2 lg:grid-cols-5"
    >
      <label className="flex flex-col text-sm">
        <span className="text-gray-700">Категория</span>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="mt-1 rounded border border-gray-300 px-2 py-1"
        >
          <option value="">Все категории</option>
          {categories.map((cat) => (
            <option key={cat.slug} value={cat.slug}>
              {cat.title}
            </option>
          ))}
        </select>
      </label>
      {isStaffAdmin ? (
        <>
          <label className="flex flex-col text-sm">
            <span className="text-gray-700">Аудитория</span>
            <input
              type="text"
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
              placeholder="tenant"
              className="mt-1 rounded border border-gray-300 px-2 py-1"
            />
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-gray-700">Язык</span>
            <input
              type="text"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              placeholder="ru"
              className="mt-1 rounded border border-gray-300 px-2 py-1"
            />
          </label>
        </>
      ) : null}
      <label className="flex flex-col text-sm sm:col-span-2">
        <span className="text-gray-700">Теги (через запятую)</span>
        <input
          type="text"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="договор, аренда"
          className="mt-1 rounded border border-gray-300 px-2 py-1"
        />
      </label>
      <div className="sm:col-span-2 lg:col-span-5 flex justify-end">
        <button
          type="submit"
          className="rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-ink hover:bg-brand-hover"
        >
          Применить
        </button>
      </div>
    </form>
  );
}

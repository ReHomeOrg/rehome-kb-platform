"use client";

/**
 * Article create/edit form (#201, ADR-0003 write extension).
 *
 * Backend constraints:
 * - Slug `^[a-z0-9-]+$`, 1..200 chars. Immutable post-create (PATCH запрещает).
 * - access_level — security-relevant; PATCH запрещает менять (security-by-design,
 *   writer не повышает visibility тихо). В edit mode эти поля disabled.
 * - Tags — string[]; UI рендерит как comma-separated input.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  createArticle,
  patchArticle,
  type ArticleAccessLevel,
  type ArticleCreateInput,
  type ArticlePatchInput,
} from "@/lib/api/articles";
import type { Article } from "@/lib/api/types";

interface Props {
  initial?: Article;
}

const ACCESS_LEVELS: ArticleAccessLevel[] = [
  "PUBLIC",
  "LOGGED",
  "AGENT",
  "STAFF",
  "LEGAL",
  "HR_RESTRICTED",
];

const STATUSES = ["DRAFT", "PUBLISHED", "ARCHIVED"];

const LANGUAGES = ["ru", "en"];

function tagsToString(tags: string[] | undefined): string {
  return (tags ?? []).join(", ");
}

function parseTags(s: string): string[] {
  return s
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export default function ArticleForm({ initial }: Props): JSX.Element {
  const router = useRouter();
  const isEdit = Boolean(initial);

  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState(initial?.body_markdown ?? "");
  const [category, setCategory] = useState(initial?.category ?? "");
  const [audience, setAudience] = useState(initial?.audience ?? "tenant");
  const [accessLevel, setAccessLevel] = useState<ArticleAccessLevel>(
    (initial?.access_level as ArticleAccessLevel) ?? "PUBLIC",
  );
  const [status, setStatus] = useState(initial?.status ?? "DRAFT");
  const [language, setLanguage] = useState(initial?.language ?? "ru");
  const [tags, setTags] = useState(tagsToString(initial?.tags));

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      if (isEdit && initial) {
        const patch: ArticlePatchInput = {
          title,
          body_markdown: body,
          tags: parseTags(tags),
          status,
        };
        const updated = await patchArticle(initial.slug, patch);
        router.push(`/articles/${encodeURIComponent(updated.slug)}`);
      } else {
        const input: ArticleCreateInput = {
          slug: slug.trim(),
          title,
          body_markdown: body,
          category,
          audience,
          access_level: accessLevel,
          status,
          language,
          tags: parseTags(tags),
        };
        const created = await createArticle(input);
        router.push(`/articles/${encodeURIComponent(created.slug)}`);
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
            Slug{" "}
            <span className="text-xs text-gray-500">
              {isEdit ? "(immutable)" : "(URL-fragment, a-z0-9-)"}
            </span>
          </span>
          <input
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            pattern="^[a-z0-9-]+$"
            minLength={1}
            maxLength={200}
            required
            disabled={isEdit}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-mono disabled:bg-gray-100"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Заголовок <span className="text-red-700">*</span>
          </span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            minLength={1}
            maxLength={200}
            required
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Категория{" "}
            <span className="text-xs text-gray-500">
              {isEdit ? "(immutable)" : ""}
            </span>
          </span>
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            minLength={1}
            maxLength={100}
            required
            disabled={isEdit}
            placeholder="onboarding / payments / faq"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:bg-gray-100"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Аудитория{" "}
            <span className="text-xs text-gray-500">
              {isEdit ? "(immutable)" : ""}
            </span>
          </span>
          <input
            type="text"
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            minLength={1}
            maxLength={16}
            required
            disabled={isEdit}
            placeholder="tenant / landlord / staff"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:bg-gray-100"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Язык</span>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            disabled={isEdit}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:bg-gray-100"
          >
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Access level{" "}
            <span className="text-xs text-gray-500">
              {isEdit ? "(immutable per ADR-0003)" : ""}
            </span>
          </span>
          <select
            value={accessLevel}
            onChange={(e) =>
              setAccessLevel(e.target.value as ArticleAccessLevel)
            }
            disabled={isEdit}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:bg-gray-100"
          >
            {ACCESS_LEVELS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Статус</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
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
        <span className="font-medium text-gray-700">
          Тэги{" "}
          <span className="text-xs text-gray-500">
            (comma-separated: tag1, tag2, tag3)
          </span>
        </span>
        <input
          type="text"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="onboarding, payments, faq"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Содержание (Markdown) <span className="text-red-700">*</span>
        </span>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={20}
          minLength={1}
          required
          placeholder="# Заголовок раздела&#10;&#10;Текст параграфа..."
          className="rounded-md border border-gray-300 px-3 py-2 font-mono text-xs"
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

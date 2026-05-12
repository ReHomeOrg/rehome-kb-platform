/**
 * /tags — облако тегов (UI.3 #79).
 *
 * Опциональный `?q=` для substring filter.
 */

import Nav from "@/app/_components/nav";
import { listTags } from "@/lib/api/tags";

import TagFilter from "./_components/tag-filter";
import TagsCloud from "./_components/tags-cloud";

interface PageProps {
  searchParams: Promise<{ q?: string }>;
}

export default async function TagsPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const { q } = await searchParams;
  const trimmed = q?.trim();
  const response = await listTags({
    q: trimmed || undefined,
    limit: 200,
  });

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Теги</h1>
          <p className="mt-1 text-sm text-gray-600">
            Облако тегов. Размер пропорционален количеству статей. Клик —
            фильтрованный список.
          </p>
        </header>
        <TagFilter initial={trimmed ?? ""} />
        <section className="rounded-md border border-gray-200 p-4">
          <TagsCloud tags={response.data} />
        </section>
      </main>
    </>
  );
}

/**
 * /articles/[slug]/edit — edit article (#201).
 *
 * Только title/body/tags/status patchable (ADR-0003 security guard).
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { getArticle } from "@/lib/api/articles";
import { ApiError } from "@/lib/api/client";

import ArticleForm from "../../_components/article-form";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export default async function ArticleEditPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { slug } = await params;
  let article;
  try {
    article = await getArticle(slug);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-8">
        <Link
          href={`/articles/${encodeURIComponent(article.slug)}`}
          className="text-sm text-gray-600 hover:underline"
        >
          ← К статье
        </Link>
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            {article.title}
          </h1>
          <p className="mt-1 text-xs text-gray-500">
            Редактирование. История изменений сохраняется в audit_log.
          </p>
        </header>
        <ArticleForm initial={article} />
      </main>
    </>
  );
}

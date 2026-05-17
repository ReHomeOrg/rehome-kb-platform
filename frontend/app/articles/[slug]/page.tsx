/**
 * /articles/[slug] — detail view.
 *
 * Server Component. Calls `getArticle(slug)`; на 404 → `notFound()` →
 * `not-found.tsx`. Render с react-markdown (без raw HTML).
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { getArticle } from "@/lib/api/articles";
import { ApiError } from "@/lib/api/client";

import ArticleMarkdown from "../_components/article-markdown";
import DeleteArticleButton from "../_components/delete-button";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export default async function ArticleDetailPage({
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
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <div className="flex items-center justify-between">
          <Link href="/articles" className="text-sm text-gray-600 hover:underline">
            ← Назад к списку
          </Link>
          <div className="flex items-center gap-2">
            <Link
              href={`/articles/${encodeURIComponent(article.slug)}/edit`}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
            >
              Редактировать
            </Link>
            <DeleteArticleButton slug={article.slug} />
          </div>
        </div>
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">
            {article.title}
          </h1>
          {article.summary ? (
            <p className="mt-2 text-base text-gray-600">{article.summary}</p>
          ) : null}
          <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-gray-500 sm:grid-cols-4">
            <div>
              <dt className="font-medium text-gray-700">Категория</dt>
              <dd>{article.category}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-700">Аудитория</dt>
              <dd>{article.audience}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-700">Язык</dt>
              <dd>{article.language}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-700">Обновлено</dt>
              <dd>{new Date(article.updated_at).toLocaleDateString("ru-RU")}</dd>
            </div>
          </dl>
          {article.tags.length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-1">
              {article.tags.map((tag) => (
                <li
                  key={tag}
                  className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700"
                >
                  {tag}
                </li>
              ))}
            </ul>
          ) : null}
        </header>
        <article className="rounded-md border border-gray-200 p-6">
          <ArticleMarkdown content={article.body_markdown} />
        </article>
      </main>
    </>
  );
}

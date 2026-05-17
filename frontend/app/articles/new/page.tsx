/**
 * /articles/new — create article (#201).
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";

import ArticleForm from "../_components/article-form";

export default function ArticleNewPage(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-8">
        <Link
          href="/articles"
          className="text-sm text-gray-600 hover:underline"
        >
          ← К списку
        </Link>
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            Новая статья
          </h1>
          <p className="mt-1 text-xs text-gray-500">
            Slug, категория и аудитория immutable после создания
            (ADR-0003 — нельзя тихо повысить access_level через PATCH).
          </p>
        </header>
        <ArticleForm />
      </main>
    </>
  );
}

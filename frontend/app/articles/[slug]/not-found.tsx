import Link from "next/link";

import Nav from "@/app/_components/nav";

export default function ArticleNotFound(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-12 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          Статья не найдена
        </h1>
        <p className="text-sm text-gray-600">
          Возможно, она была удалена, или у вас нет к ней доступа.
        </p>
        <Link
          href="/articles"
          className="mx-auto rounded-md border border-gray-300 px-4 py-1.5 text-sm hover:bg-gray-50"
        >
          ← К списку статей
        </Link>
      </main>
    </>
  );
}

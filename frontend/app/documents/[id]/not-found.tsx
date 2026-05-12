import Link from "next/link";

import Nav from "@/app/_components/nav";

export default function DocumentNotFound(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-12 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          Документ не найден
        </h1>
        <p className="text-sm text-gray-600">
          Возможно, он был удалён, или у вас нет к нему доступа.
        </p>
        <Link
          href="/documents"
          className="mx-auto rounded-md border border-gray-300 px-4 py-1.5 text-sm hover:bg-gray-50"
        >
          ← К списку документов
        </Link>
      </main>
    </>
  );
}

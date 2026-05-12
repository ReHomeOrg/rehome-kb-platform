/**
 * /categories — дерево категорий (UI.3 #79).
 */

import Nav from "@/app/_components/nav";
import { listCategories } from "@/lib/api/categories";

import CategoryTree from "./_components/category-tree";

export default async function CategoriesPage(): Promise<JSX.Element> {
  const response = await listCategories();

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Категории</h1>
          <p className="mt-1 text-sm text-gray-600">
            Иерархия разделов базы знаний. Клик по категории — список статей.
          </p>
        </header>
        <section className="rounded-md border border-gray-200 p-4">
          <CategoryTree nodes={response.data} />
        </section>
      </main>
    </>
  );
}

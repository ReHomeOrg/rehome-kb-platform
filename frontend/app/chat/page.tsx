/**
 * /chat — список недавних сессий + кнопка создать новую.
 */

import Nav from "@/app/_components/nav";

import NewSessionButton from "./_components/new-session-button";
import SessionList from "./_components/session-list";

export default function ChatHomePage(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">AI-чат</h1>
          <p className="mt-1 text-sm text-gray-600">
            Помощник по вопросам аренды жилья reHome.
          </p>
        </header>
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-gray-700">Новая сессия</h2>
          <NewSessionButton />
        </section>
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-gray-700">Недавние сессии</h2>
          <SessionList />
        </section>
      </main>
    </>
  );
}

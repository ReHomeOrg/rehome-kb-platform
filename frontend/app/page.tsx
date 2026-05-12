import { cookies } from "next/headers";

import { COOKIE_SESSION } from "@/lib/auth/cookies";

export default async function Home() {
  const cookieStore = await cookies();
  const isLoggedIn = cookieStore.has(COOKIE_SESSION);

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        help.rehome.one
      </h1>
      <p className="mt-4 text-lg text-gray-600">
        База знаний reHome — справочник, политики, FAQ и помощник по аренде жилья.
      </p>
      <p className="mt-8 inline-flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-4 py-2 text-sm text-gray-600">
        🚧 Coming soon — контент наполняется в Phase 1, E3.
      </p>

      <div className="mt-10">
        {isLoggedIn ? (
          <form action="/api/auth/logout" method="post">
            <button
              type="submit"
              className="inline-flex items-center rounded-md border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
            >
              Выйти
            </button>
          </form>
        ) : (
          <a
            href="/login"
            className="inline-flex items-center rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
          >
            Войти
          </a>
        )}
      </div>
    </main>
  );
}

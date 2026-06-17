/**
 * Login page — минимальный UI с одной кнопкой redirect на /api/auth/login.
 */

import { BASE_PATH } from "@/lib/base-path";

export default function LoginPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">
        Вход в reHome KB
      </h1>
      <p className="mt-3 text-gray-600">
        Авторизация через единый SSO платформы reHome (Keycloak).
      </p>
      <div className="mt-8">
        <a
          href={`${BASE_PATH}/api/auth/login`}
          className="inline-flex items-center rounded-md bg-brand px-5 py-2.5 text-sm font-medium text-white hover:bg-brand-hover"
        >
          Войти через reHome SSO
        </a>
      </div>
      <p className="mt-12 text-xs text-gray-500">
        После входа вы будете перенаправлены на главную.
      </p>
    </main>
  );
}

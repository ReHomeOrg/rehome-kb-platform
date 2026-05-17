/**
 * /vault — менеджер паролей (ADR-0011 + ADR-0016 Slice 1).
 *
 * Server Component fetch'ит `/vault/me` для определения is_setup / is_2fa.
 * Сам unlock/setup state живёт client-side в lib/vault/session.ts.
 */

import { redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getCurrentUserId, getVaultMe } from "@/lib/api/vault";

import VaultShell from "./_components/vault-shell";

export const dynamic = "force-dynamic";

export default async function VaultPage(): Promise<JSX.Element> {
  let me;
  let userId: string;
  try {
    [me, userId] = await Promise.all([getVaultMe(), getCurrentUserId()]);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      redirect("/login");
    }
    throw err;
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            Менеджер паролей
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Корпоративный vault для секретов (SSH, API-ключи, банкинг,
            КЭП-токены). Zero-knowledge: master password никогда не
            покидает браузер (ADR-0011).
          </p>
        </header>
        <VaultShell me={me} userId={userId} />
      </main>
    </>
  );
}

/**
 * /admin/vault/emergency-unlock — emergency recovery ceremony (ADR-0021 A).
 *
 * staff_admin scope (backend gate STAFF + LEGAL). Non-admin → backend
 * returns 403 → graceful UX error в EmergencyUnlockForm.
 *
 * Не Server Component: ceremony требует client-side crypto (SubtleCrypto +
 * Shamir combine). Page просто mounts client form.
 */

import Nav from "@/app/_components/nav";

import EmergencyUnlockForm from "./_components/emergency-unlock-form";

export const dynamic = "force-dynamic";

export default function EmergencyUnlockPage(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            Emergency vault unlock
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Ceremony per ADR-0021 — Shamir 2-of-2 share combine + client-side
            decrypt. Каждое использование создаёт security_incident +
            audit row. Backend никогда не видит shares.
          </p>
        </header>
        <EmergencyUnlockForm />
      </main>
    </>
  );
}

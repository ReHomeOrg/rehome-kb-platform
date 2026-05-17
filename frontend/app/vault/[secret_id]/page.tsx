/**
 * /vault/[secret_id] — отдельная карточка секрета (ADR-0016 Slice 2).
 *
 * Server Component — простой shell. Decrypt + UI — client component
 * (требует vaultKey из in-memory session).
 */

import Link from "next/link";
import { redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getCurrentUserId } from "@/lib/api/vault";

import SecretDetail from "../_components/secret-detail";

interface PageProps {
  params: Promise<{ secret_id: string }>;
}

export default async function VaultSecretPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { secret_id } = await params;
  let userId: string;
  try {
    userId = await getCurrentUserId();
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
        <Link href="/vault" className="text-sm text-gray-600 hover:underline">
          ← К vault
        </Link>
        <SecretDetail secretId={secret_id} userId={userId} />
      </main>
    </>
  );
}

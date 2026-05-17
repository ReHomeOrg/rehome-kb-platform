/**
 * /vault/[secret_id] — отдельная карточка секрета (ADR-0016 Slice 2).
 *
 * Server Component — простой shell. Decrypt + UI — client component
 * (требует vaultKey из in-memory session).
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";

import SecretDetail from "../_components/secret-detail";

interface PageProps {
  params: Promise<{ secret_id: string }>;
}

export default async function VaultSecretPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { secret_id } = await params;
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <Link href="/vault" className="text-sm text-gray-600 hover:underline">
          ← К vault
        </Link>
        <SecretDetail secretId={secret_id} />
      </main>
    </>
  );
}

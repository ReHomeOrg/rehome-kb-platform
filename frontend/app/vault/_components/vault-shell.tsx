"use client";

/**
 * Vault shell — client-side router между setup/unlock/unlocked состояниями.
 *
 * Server Component (page.tsx) fetch'ит /vault/me, передаёт сюда initial
 * state. Дальше клиент сам решает что показать на основе локального
 * `isUnlocked()` (vaultKey в памяти) + initial `is_setup` от сервера.
 *
 * Slice 1 — после unlock'а просто отображает «Vault unlocked» placeholder
 * + кнопку lock. Реальный secrets-list — Slice 2.
 */

import { useEffect, useState } from "react";

import type { VaultMeView } from "@/lib/api/vault";
import { isUnlocked, subscribe } from "@/lib/vault/session";

import SetupForm from "./setup-form";
import UnlockedView from "./unlocked-view";
import UnlockForm from "./unlock-form";

interface Props {
  me: VaultMeView;
  userId: string;
}

export default function VaultShell({ me, userId }: Props): JSX.Element {
  const [unlocked, setUnlocked] = useState(isUnlocked());

  useEffect(() => {
    return subscribe(() => setUnlocked(isUnlocked()));
  }, []);

  if (!me.is_setup) {
    return (
      <section className="rounded-md border border-gray-200 p-6">
        <h2 className="text-lg font-semibold">Создание vault</h2>
        <p className="mt-1 text-xs text-gray-500">
          Vault ещё не настроен. Создайте master password — он будет
          использован для шифрования всех секретов локально (zero-knowledge,
          ADR-0011).
        </p>
        <div className="mt-4">
          <SetupForm />
        </div>
      </section>
    );
  }

  if (!unlocked) {
    return (
      <section className="rounded-md border border-gray-200 p-6">
        <h2 className="text-lg font-semibold">Разблокировка vault</h2>
        {me.last_unlock_at ? (
          <p className="mt-1 text-xs text-gray-500">
            Последняя успешная разблокировка:{" "}
            {new Date(me.last_unlock_at).toLocaleString("ru-RU")}
          </p>
        ) : null}
        <div className="mt-4">
          <UnlockForm
            argonSaltB64={me.argon_salt_b64 ?? ""}
            hasTotp={me.has_totp}
            totpSecretEncryptedB64={me.totp_secret_encrypted_b64}
          />
        </div>
      </section>
    );
  }

  return (
    <UnlockedView
      userId={userId}
      hasTotp={me.has_totp}
      argonSaltB64={me.argon_salt_b64 ?? ""}
    />
  );
}

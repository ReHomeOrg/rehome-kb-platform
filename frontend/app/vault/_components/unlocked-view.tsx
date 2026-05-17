"use client";

/**
 * Unlocked vault view (ADR-0016 Slice 2).
 *
 * Compoposes:
 * - Lock button.
 * - CreateSecretForm (toggle).
 * - SecretsList (decrypts titles).
 *
 * Создание / удаление trigger'ит reload через `reloadToken` bump.
 */

import { useState } from "react";

import { lock, touch } from "@/lib/vault/session";

import CreateSecretForm from "./create-secret-form";
import SecretsList from "./secrets-list";

interface Props {
  userId: string;
}

export default function UnlockedView({ userId }: Props): JSX.Element {
  const [showCreate, setShowCreate] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  return (
    <section
      className="flex flex-col gap-4 rounded-md border border-green-300 bg-green-50 p-6"
      onClick={() => touch()}
    >
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-green-900">
            Vault разблокирован
          </h2>
          <p className="text-xs text-green-800">
            Auto-lock через 15 минут бездействия. Каждый просмотр секрета
            журналируется на сервере (ПЗ §8).
          </p>
        </div>
        <button
          type="button"
          onClick={() => lock()}
          className="shrink-0 rounded-md border border-green-300 bg-white px-3 py-1.5 text-sm font-medium text-green-800 hover:bg-green-100"
        >
          Заблокировать
        </button>
      </header>

      <div className="rounded-md bg-white p-4">
        {showCreate ? (
          <CreateSecretForm
            userId={userId}
            onCancel={() => setShowCreate(false)}
            onSuccess={() => {
              setShowCreate(false);
              setReloadToken((n) => n + 1);
            }}
          />
        ) : null}
        <SecretsList
          onCreateClick={() => setShowCreate(true)}
          reloadToken={reloadToken}
        />
      </div>
    </section>
  );
}

"use client";

/**
 * Vault unlock form (ADR-0016 Slice 1).
 *
 * Берёт argon_salt из `/vault/me` response, derive'ит vaultKey + authHash
 * локально, отправляет authHash на `/vault/unlock`. На success — store'ит
 * vaultKey в session.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { unlockVault } from "@/lib/api/vault";
import { deriveKeys, fromBase64, toBase64 } from "@/lib/vault/crypto";
import { setVaultKey } from "@/lib/vault/session";

interface Props {
  argonSaltB64: string;
}

export default function VaultUnlockForm({ argonSaltB64 }: Props): JSX.Element {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);
    if (password.length === 0) {
      setError("Введите master password");
      return;
    }
    setPending(true);
    try {
      const salt = fromBase64(argonSaltB64);
      const { vaultKey, authHash } = await deriveKeys(password, salt);
      await unlockVault({ auth_hash_b64: toBase64(authHash) });
      // Success → vaultKey valid (server hash совпал), store локально.
      setVaultKey(vaultKey);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Неверный master password");
      } else if (err instanceof ApiError) {
        setError(`${err.status}: ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : "Ошибка");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <p className="text-sm text-gray-600">
        Vault уже создан. Введите master password — он будет использован
        локально для расшифровки секретов. На сервер передаётся только
        hash от пароля для проверки.
      </p>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Master password <span className="text-red-700">*</span>
        </span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          autoFocus
        />
      </label>
      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="self-start rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
      >
        {pending ? "Разблокируем…" : "Разблокировать"}
      </button>
    </form>
  );
}

"use client";

/**
 * Initial vault setup form (ADR-0016 Slice 1).
 *
 * Generates argon_salt + X25519 keypair locally, derives vaultKey +
 * authHash from master password (Argon2id), wraps privkey under vaultKey,
 * POSTs encrypted state to backend. После успеха вызывает setVaultKey
 * → vault unlocked locally.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { setupVault } from "@/lib/api/vault";
import {
  deriveKeys,
  generateSalt,
  generateX25519Keypair,
  toBase64,
  wrapX25519Privkey,
} from "@/lib/vault/crypto";
import { setVaultKey } from "@/lib/vault/session";

const MIN_PASSWORD_LENGTH = 12;

export default function VaultSetupForm(): JSX.Element {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);

    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Пароль должен быть не короче ${MIN_PASSWORD_LENGTH} символов`);
      return;
    }
    if (password !== confirm) {
      setError("Пароли не совпадают");
      return;
    }
    if (!acknowledged) {
      setError(
        "Подтвердите понимание: восстановить vault при потере master password невозможно",
      );
      return;
    }

    setPending(true);
    try {
      const salt = generateSalt();
      const { vaultKey, authHash } = await deriveKeys(password, salt);
      const keypair = generateX25519Keypair();
      const wrappedPrivkey = await wrapX25519Privkey(vaultKey, keypair.privkey);

      await setupVault({
        argon_salt_b64: toBase64(salt),
        auth_hash_b64: toBase64(authHash),
        encrypted_x25519_privkey_b64: toBase64(wrappedPrivkey),
        x25519_pubkey_b64: toBase64(keypair.pubkey),
      });

      // Setup success → vault уже unlocked локально, нужно lift state.
      setVaultKey(vaultKey);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as { detail?: unknown } | null;
        setError(
          typeof body?.detail === "string"
            ? `${err.status}: ${body.detail}`
            : `${err.status}: ${err.message}`,
        );
      } else {
        setError(err instanceof Error ? err.message : "Ошибка setup");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <p className="rounded-md border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-900">
        <strong>Важно.</strong> Master password шифрует все ваши секреты
        локально и никогда не отправляется на сервер. <strong>Восстановить
        vault при потере master password невозможно</strong> — все секреты
        будут безвозвратно потеряны. Выберите надёжный пароль и запомните
        его / запишите в безопасное место.
      </p>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Master password <span className="text-red-700">*</span>{" "}
          <span className="text-xs text-gray-500">
            (не короче {MIN_PASSWORD_LENGTH} символов)
          </span>
        </span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={MIN_PASSWORD_LENGTH}
          required
          autoComplete="new-password"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Подтвердите master password <span className="text-red-700">*</span>
        </span>
        <input
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          minLength={MIN_PASSWORD_LENGTH}
          required
          autoComplete="new-password"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
      </label>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(e) => setAcknowledged(e.target.checked)}
          className="mt-1"
        />
        <span>
          Я понимаю, что master password не подлежит восстановлению, и
          беру на себя ответственность за его хранение.
        </span>
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
        {pending ? "Создаём vault…" : "Создать vault"}
      </button>
    </form>
  );
}
